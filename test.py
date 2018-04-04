import os
from options.test_options import TestOptions
import torch
from torch.autograd import Variable
import numpy as np
from PIL import Image
from torch.utils.data import DataLoader, Dataset
from torchvision.transforms import ToTensor,Normalize,ToPILImage
from PIL import Image
from utils import evalIoU
from utils.label2Img import label2rgb
from networks.network import *
import time


def load_image(file):
    return Image.open(file)

class Transform_test(object):
    def __init__(self,height=832):
        self.height = height
        pass
    def __call__(self, input, target):
        # do something to both images 
        input =  input.resize((448,320), Image.BILINEAR)
        target = target.resize((448,320),Image.NEAREST)

        target = torch.from_numpy(np.array(target)).long().unsqueeze(0)

        input_tensor = ToTensor()(input)  
        Normalize([.485, .456, .406], [.229, .224, .225])(input_tensor)
        return input_tensor, target, input


class NeoData_test(Dataset):
    def __init__(self, transform=None, testimage=None, testlabel=None):
        self.data = testimage
        self.label = testlabel
        self.transform = transform 

    def __getitem__(self, index):
        filename = self.data[index]
        filenameGt = self.label[index]
        with open(filename, 'rb') as f: # advance
            image = load_image(f).convert('RGB')
        with open(filenameGt, 'rb') as f:
            label = load_image(f).convert('P')

        if self.transform is not None:
            image_tensor, label_tensor, img = self.transform(image, label)

        return (image_tensor, label_tensor, np.array(img))

    def __len__(self):
        return len(self.data)

def main(args):
    ######## load the test data ##########    
    datadir = os.path.join(args.datadir, 'image.txt')
    despath = args.savedir
    
    if not os.path.exists(despath):
        os.mkdir(despath)

    testimage = []
    with open(datadir) as f:
        for line in f:
            testimage.append(line.strip().replace('\n',''))


    def trans(testimage):   #In my datasets, no all the images are '.png', so  
        testlabel = []
        for i in testimage:
            if i.endswith('.png'):
                testlabel.append(i.replace('leftImg8bit','gtFine').replace('.png','_label.png'))
            else:
                testlabel.append(i.replace('leftImg8bit','gtFine').replace('.jpg','_label.png'))
        return testlabel

    testlabel = trans(testimage)
    print("length of testimage and its label: {}".format(len(testimage)))


    transform = Transform_test()#832
    dataset_test = NeoData_test(transform, testimage, testlabel)
    loader = DataLoader(dataset_test, num_workers=4, batch_size=1,shuffle=False)



    ############################ eval the result of IoU

    time_train = []
    confMatrix = evalIoU.generateMatrixTrainId(evalIoU.args)
    perImageStats = {}
    nbPixels = 0
    usedLr = 0

    net_dic = {'erfnet' : ERFNet, 'fcn8' : FCN8, 'fcn16' : FCN16, 
                'fcn32' : FCN32, 'unet' : UNet, 'pspnet': PSPNet, 'segnet' : SegNet}
    Net = net_dic[args.model]
    
    model = Net(args.num_classes)
    if args.cuda:
        model = Net(args.num_classes).cuda()
    else:
        model = Net(args.num_classes)

    model.load_state_dict(torch.load(args.model_dir))
    model.eval()

    count = 0
    for step, colign in enumerate(zip(loader,testimage)):

      img = colign[0][2]
      img = np.array(img).squeeze(0)
      start_time = time.time()
      
      images = colign[0][0]   #image
      label = colign[0][1]    #label

      temp  = label
      if args.cuda:
        images = images.cuda()
      inputs = Variable(images,volatile=True)

      outputs = model(inputs)
      out = outputs[0].cpu().max(0)[1].data.squeeze(0).byte().numpy() #index of max-channel 

      print('forward the net cost : ',time.time()-start_time)

      # do IoU 
      if isinstance(outputs,list):
        #compatibility with critetion dataparallel
        outputs_cpu = outputs[0].cpu()
        for i in range(1,len(outputs)):   #merge gpu tensor
          outputs_cpu = torch.cat((outputs_cpu, outputs[i].cpu()), 0)
      else:
        outputs_cpu = outputs.cpu() 

      for i in range(0,outputs_cpu.size(0)):
        prediction = ToPILImage()(outputs_cpu[i].max(0)[1].data.unsqueeze(0).byte())
        groundtruth = ToPILImage()(label[i].cpu().byte())

        print("prediction size is : {} groundtruth size is : {}".format(prediction.size, groundtruth.size))

        nbPixels += evalIoU.evaluatePairPytorch(prediction,groundtruth,confMatrix,perImageStats,evalIoU.args)


      label2img = label2rgb(out,img)   #result adding to origin picture
      Image.fromarray(label2img).save(despath + '_label2img_' + colign[1].strip().split('/')[-1])

      for k in range(out.shape[0]):
        for j in range(out.shape[1]):
          if out[k,j] == 0 : 
           img[k,j,:]=0


      start_time = time.time()
      #Image.fromarray(img).save(despath+'encoderDecoder_'+str(count)+'.png')
      Image.fromarray(img).save(despath+colign[1].strip().split('/')[-1])     #cutting out segmented area
      count += 1
      print("This is the {}th of image!".format(count))

    iouTest = 0
    classScoreList = {}
    for label in evalIoU.args.evalLabels:
        labelName = evalIoU.trainId2label[label].name
        classScoreList[labelName] = evalIoU.getIouScoreForTrainLabel(label, confMatrix,evalIoU.args)
    iouAvgStr = evalIoU.getColorEntry(evalIoU.getScoreAverage(classScoreList, evalIoU.args),evalIoU.args) + "{avg:5.3f}".format(avg=evalIoU.getScoreAverage(classScoreList, evalIoU.args)) + evalIoU.args.nocol
    iouTrain = float(evalIoU.getScoreAverage(classScoreList,evalIoU.args))
    print("IoU on TEST set : ",iouAvgStr)
    print("IoU on TEST set of each class - car:{}  light:{} ".format(classScoreList['car'],classScoreList['light']))

if __name__ == '__main__':

    parser = TestOptions().parse()
    main(parser)


