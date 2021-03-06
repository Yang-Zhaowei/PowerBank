"""Adapted from:
    @longcw faster_rcnn_pytorch: https://github.com/longcw/faster_rcnn_pytorch
    @rbgirshick py-faster-rcnn https://github.com/rbgirshick/py-faster-rcnn
    Licensed under The MIT License [see LICENSE for details]
"""

from __future__ import print_function
import os
from cv2 import cv2
import sys
import time

import torch
import argparse
import numpy as np
import pickle
from tqdm import tqdm

from data import *
from data import PB_CLASSES as labelmap
from config import pb300, pb512
from model_ssd import build_ssd

sys.path.append(os.getcwd())


def str2bool(v):
    return v.lower() in ("yes", "true", "t", "1")


parser = argparse.ArgumentParser(
    description='Single Shot MultiBox Detector Evaluation')
parser.add_argument('--testset_filename', default='sub_test_core_coreless.txt',
                    type=str, help='image names in test set(.txt file)')  # 测试图片名的txt文档
parser.add_argument('--image_path', default='../data/test/Image_test/',
                    type=str, help='Path of images')  # 图片文件夹
parser.add_argument('--anno_path', default='../data/test/Anno_test/',
                    type=str, help='Path of annotation files')  # 标注文件夹
parser.add_argument('--min_dim', default=512, type=int,
                    help='Min dim of Input')
parser.add_argument('--trained_model',
                    default=None, type=str,
                    help='Trained state_dict file path to open')
parser.add_argument('--save_folder', default='eval/', type=str,
                    help='File path to save results')
parser.add_argument('--confidence_threshold', default=0.01, type=float,
                    help='Detection confidence threshold')
parser.add_argument('--top_k', default=5, type=int,
                    help='Further restrict the number of predictions to parse')
parser.add_argument('--cuda', default=True, type=str2bool,
                    help='Use cuda to train model')
parser.add_argument('--over_thresh', default=0.5, type=float,
                    help='Cleanup and remove results files following eval')
args = parser.parse_args()

if not os.path.exists(args.save_folder):
    os.mkdir(args.save_folder)


class Timer(object):
    """A simple timer."""

    def __init__(self):
        self.total_time = 0.
        self.calls = 0
        self.start_time = 0.
        self.diff = 0.
        self.average_time = 0.

    def tic(self):
        # using time.time instead of time.clock because time time.clock
        # does not normalize for multithreading
        self.start_time = time.time()

    def toc(self, average=True):
        self.diff = time.time() - self.start_time
        self.total_time += self.diff
        self.calls += 1
        self.average_time = self.total_time / self.calls
        if average:
            return self.average_time
        else:
            return self.diff


def parse_rec(filename, width, height):
    """ Parse a Powerbank Annotation txt file """
    objects = []
    with open(filename, "r", encoding='utf-8') as f1:
        dataread = f1.readlines()
        for annotation in dataread:
            obj_struct = {}
            temp = annotation.split()
            name = temp[1]
            if name != '带电芯充电宝' and name != '不带电芯充电宝':
                continue
            xmin = int(temp[2])
            if int(xmin) > width:
                continue
            if xmin < 0:
                xmin = 1
            ymin = int(temp[3])
            if ymin < 0:
                ymin = 1
            xmax = int(temp[4])
            if xmax > width:
                xmax = width - 1
            ymax = int(temp[5])
            if ymax > height:
                ymax = height - 1
            ##name
            obj_struct['name'] = name
            obj_struct['pose'] = 'Unspecified'
            obj_struct['truncated'] = 0
            obj_struct['difficult'] = 0
            obj_struct['bbox'] = [float(xmin) - 1,
                                  float(ymin) - 1,
                                  float(xmax) - 1,
                                  float(ymax) - 1]
            objects.append(obj_struct)

    return objects


def get_output_dir(name, phase):
    """Return the directory where experimental artifacts are placed.
    If the directory does not exist, it is created.
    A canonical path is built using the name from an imdb and a network
    (if not None).
    """
    filedir = os.path.join(name, phase)
    if not os.path.exists(filedir):
        os.makedirs(filedir)
    return filedir


def get_voc_results_file_template(data_dir, image_set, cls):
    filename = 'result' + '_%s.txt' % (cls)
    filedir = os.path.join(data_dir, 'results')
    if not os.path.exists(filedir):
        os.makedirs(filedir)
    path = os.path.join(filedir, filename)
    return path


def write_voc_results_file(data_dir, all_boxes, dataset, set_type):
    for cls_ind, cls in enumerate(labelmap):
        #get any class to store the result
        filename = get_voc_results_file_template(data_dir, set_type, cls)
        with open(filename, 'wt') as f:
            for im_ind, index in enumerate(dataset.ids):
                dets = all_boxes[cls_ind+1][im_ind]
                if dets == []:
                    continue
                for k in range(dets.shape[0]):
                    f.write('{:s} {:.3f} {:.1f} {:.1f} {:.1f} {:.1f}\n'.
                            format(index.split('/')[-1].split('.')[0], dets[k, -1],
                                   dets[k, 0] + 1, dets[k, 1] + 1,
                                   dets[k, 2] + 1, dets[k, 3] + 1))


def do_python_eval(output_dir, set_type, use_07=False):
    cachedir = os.path.join(output_dir, 'annotations_cache')
    imgsetpath = args.testset_filename
    imgspath = args.image_path
    annopath = args.anno_path
    if not os.path.isdir(cachedir):
        os.mkdir(cachedir)
    aps = []

    for i, cls in enumerate(labelmap):
        filename = get_voc_results_file_template(output_dir, set_type, cls)
        rec, prec, ap = voc_eval(
            filename, annopath, imgspath, imgsetpath.format(
                set_type), cls, cachedir,
            ovthresh=args.over_thresh, use_07_metric=use_07)
        aps += [ap]
        print('AP for {} = {:.4f}'.format(cls, ap))

    print('Mean AP = {:.4f}'.format(np.mean(aps)))
    print('~~~~~~~~')
    print('Results:')
    for ap in aps:
        print('{:.3f}'.format(ap))
    print('{:.3f}'.format(np.mean(aps)))
    print('~~~~~~~~')
    print('')
    print('--------------------------------------------------------------')
    print('Results computed with the **unofficial** Python eval code.')
    print('Results should be very close to the official MATLAB eval code.')
    print('--------------------------------------------------------------')
    return np.mean(aps)


def voc_ap(rec, prec, use_07_metric=False):
    """ ap = voc_ap(rec, prec, [use_07_metric])
    Compute VOC AP given precision and recall.
    If use_07_metric is true, uses the
    VOC 07 11 point method (default:True).
    """
    if use_07_metric:
        # 11 point metric
        ap = 0.
        for t in np.arange(0., 1.1, 0.1):
            if np.sum(rec >= t) == 0:
                p = 0
            else:
                p = np.max(prec[rec >= t])
            ap = ap + p / 11.
        print('ERROR!')
    else:
        # correct AP calculation
        # first append sentinel values at the end
        mrec = np.concatenate(([0.], rec, [1.]))
        mpre = np.concatenate(([0.], prec, [0.]))

        # compute the precision envelope
        for i in range(mpre.size - 1, 0, -1):
            mpre[i - 1] = np.maximum(mpre[i - 1], mpre[i])

        # to calculate area under PR curve, look for points
        # where X axis (recall) changes value
        i = np.where(mrec[1:] != mrec[:-1])[0]

        # and sum (\Delta recall) * prec
        ap = np.sum((mrec[i + 1] - mrec[i]) * mpre[i + 1])
    return ap


def voc_eval(detpath,
             annopath,
             imgspath,
             imagesetfile,
             classname,
             cachedir,
             ovthresh=0.5,
             use_07_metric=False):
    """rec, prec, ap = voc_eval(detpath,
                           annopath,
                           imagesetfile,
                           classname,
                           [ovthresh],
                           [use_07_metric])
Top level function that does the PASCAL VOC evaluation.
detpath: Path to detections
   detpath.format(classname) should produce the detection results file.
annopath: Path to annotations
   annopath.format(imagename) should be the xml annotations file.
imagesetfile: Text file containing the list of images, one image per line.
classname: Category name (duh)
cachedir: Directory for caching the annotations
[ovthresh]: Overlap threshold (default = 0.5)
[use_07_metric]: Whether to use VOC07's 11 point AP computation
   (default True)
"""
# assumes detections are in detpath.format(classname)
# assumes annotations are in annopath.format(imagename)
# assumes imagesetfile is a text file with each line an image name
# cachedir caches the annotations in a pickle file
# first load gt
    cachefile = os.path.join(cachedir, args.testset_filename.split(
        '/')[-1].split('.')[0]+'annots.pkl')
    # read list of images
    with open(imagesetfile, 'r') as f:
        lines = f.readlines()
    imagenames = [x.strip() for x in lines]
    # save the truth data as pickle,if the pickle in the file, just load it.
    if not os.path.isfile(cachefile):
        #load annots
        recs = {}
        for i, imagename in enumerate(imagenames):
            filename = os.path.join(annopath, imagename+'.txt')
            imgpath = os.path.join(imgspath, imagename+'.jpg')
            img = cv2.imread(imgpath)
            height, width, channels = img.shape
            recs[imagename] = parse_rec(filename, width, height)

        # 保存testset中所有图片标注信息，方便下次使用
        print('Saving cached annotations to {:s}'.format(cachefile))
        with open(cachefile, 'wb') as f:
            pickle.dump(recs, f)
    else:
        # load
        with open(cachefile, 'rb') as f:
            recs = pickle.load(f)

    # extract gt objects for this class
    class_recs = {}
    npos = 0
    for imagename in imagenames:

        R = [obj for obj in recs[imagename] if obj['name'] == classname]
        bbox = np.array([x['bbox'] for x in R])
        difficult = np.array([x['difficult'] for x in R]).astype(np.bool)
        det = [False] * len(R)
        npos = npos + sum(~difficult)
        class_recs[imagename] = {'bbox': bbox,
                                 'difficult': difficult,
                                 'det': det}

    # read dets
    detfile = detpath.format(classname)
    with open(detfile, 'r') as f:
        lines = f.readlines()
    num = open('eval{}.txt'.format(
        args.trained_model.split('/')[-1].rsplit('.', 1)[0]), 'a+',encoding='utf-8')
    if any(lines) == 1:

        splitlines = [x.strip().split(' ') for x in lines]
        image_ids = [x[0] for x in splitlines]
        confidence = np.array([float(x[1]) for x in splitlines])
        BB = np.array([[float(z) for z in x[2:]] for x in splitlines])

        # sort by confidence
        sorted_ind = np.argsort(-confidence)
        sorted_scores = np.sort(-confidence)
        BB = BB[sorted_ind, :]
        # name=zip(list(class_recs.keys()),[0 for i in class_recs.keys()])
        image_ids = [image_ids[x] for x in sorted_ind]

        # go down dets and mark TPs and FPs
        nd = len(image_ids)
        tp = np.zeros(nd)
        fp = np.zeros(nd)
        for d in range(nd):
            R = class_recs[image_ids[d]]
            bb = BB[d, :].astype(float)
            ovmax = -np.inf
            BBGT = R['bbox'].astype(float)
            if BBGT.size > 0:
                # compute overlaps
                # intersection
                ixmin = np.maximum(BBGT[:, 0], bb[0])
                iymin = np.maximum(BBGT[:, 1], bb[1])
                ixmax = np.minimum(BBGT[:, 2], bb[2])
                iymax = np.minimum(BBGT[:, 3], bb[3])
                iw = np.maximum(ixmax - ixmin, 0.)
                ih = np.maximum(iymax - iymin, 0.)
                inters = iw * ih
                uni = ((bb[2] - bb[0]) * (bb[3] - bb[1]) +
                       (BBGT[:, 2] - BBGT[:, 0]) *
                       (BBGT[:, 3] - BBGT[:, 1]) - inters)
                overlaps = inters / uni
                ovmax = np.max(overlaps)
                jmax = np.argmax(overlaps)

            # IOU > overthresh 0.5
            if ovmax > ovthresh:
                if not R['difficult'][jmax]:
                    if not R['det'][jmax]:
                        tp[d] = 1.
                        R['det'][jmax] = 1
                    else:
                        fp[d] = 1.
            else:
                fp[d] = 1.

        for i in class_recs.keys():
            for j, flag in enumerate(class_recs[i]['det']):
                if flag == False:
                    num.write("{} {} {}\n".format(
                        i, class_recs[i]['bbox'][j], classname))

        # compute precision recall
        fp = np.cumsum(fp)
        tp = np.cumsum(tp)
        rec = tp / float(npos)
        # avoid divide by zero in case the first detection matches a difficult
        # ground truth
        prec = tp / np.maximum(tp + fp, np.finfo(np.float64).eps)
        ap = voc_ap(rec, prec, use_07_metric)
        num.write("rec:{:.5f}\tprec:{:.5f}\t tp:{}\t fp:{} \t npos:{}\n".format(
            rec[-1], prec[-1], tp[-1], fp[-1], npos))
        num.close()
    else:
        rec = -1.
        prec = -1.
        ap = -1.

    return rec, prec, ap


def test_net(save_folder, net, cuda, dataset, top_k, im_size=300, thresh=0.05):
    num_images = len(dataset)
    all_boxes = [[[] for _ in range(num_images)]
                 for _ in range(len(labelmap)+1)]
    # timers
    _t = {'im_detect': Timer(), 'misc': Timer()}
    for i in tqdm(range(num_images)):
        with torch.no_grad():
            im, gt, h, w = dataset.pull_item(i)
            img_id, annotation = dataset.pull_anno(i)
            name = img_id.split('/')[-1].split('.')[0]
            x = im.unsqueeze(0)
            if args.cuda:
                x = x.cuda()
            _t['im_detect'].tic()
            detections = net(x, 'test').data
            detect_time = _t['im_detect'].toc(average=False)

            # skip j = 0, because it's the background class
            for j in range(1, detections.size(1)):
                dets = detections[0, j, :]
                mask = dets[:, 0].gt(0.).expand(5, dets.size(0)).t()
                dets = torch.masked_select(dets, mask).view(-1, 5)
                if dets.size(0) == 0:
                    continue
                boxes = dets[:, 1:]
                boxes[:, 0] *= w
                boxes[:, 2] *= w
                boxes[:, 1] *= h
                boxes[:, 3] *= h
                scores = dets[:, 0].cpu().numpy()
                cls_dets = np.hstack((boxes.cpu().numpy(),
                                      scores[:, np.newaxis])).astype(np.float32,
                                                                     copy=False)
                all_boxes[j][i] = cls_dets
    return all_boxes


def evaluate_detections(data_dir, box_list, dataset, eval_type='test'):
    #write the det result to dir
    write_voc_results_file(data_dir, box_list, dataset, eval_type)
    return do_python_eval(data_dir, eval_type, use_07=False)


if __name__ == '__main__':
    if torch.cuda.is_available():
        if args.cuda:
            torch.set_default_tensor_type('torch.cuda.FloatTensor')
        if not args.cuda:
            print("WARNING: It looks like you have a CUDA device, but aren't using \
                  CUDA.  Run with --cuda for optimal eval speed.")
            torch.set_default_tensor_type('torch.FloatTensor')
    else:
        torch.set_default_tensor_type('torch.FloatTensor')
    num_classes = len(labelmap) + 1                      # +1 for background
    if args.min_dim == 512:
        cfg = pb512
    else:
        cfg = pb300
    net = build_ssd('test', size=cfg['min_dim'],
                    cfg=cfg)            # initialize SSD
    net.load_state_dict(torch.load(args.trained_model))

    print('Finished loading model : {}!'.format(
        args.trained_model.split('/')[-1]))
    # load data
    dataset = PBDetection(image_path=args.image_path, anno_path=args.anno_path,
                          transform=BaseTransform(cfg['min_dim'], cfg['mean'], cfg['std']))
    if args.cuda:
        net = net.cuda()
    net.eval()

    # evaluation
    cache_dir = args.save_folder
    if not os.path.exists(cache_dir):
        os.mkdir(cache_dir)

    all_boxes = test_net(args.save_folder, net, args.cuda, dataset, args.top_k, cfg['min_dim'],
                         thresh=args.confidence_threshold)

    print('Evaluating detections')
    result = evaluate_detections(cache_dir, all_boxes, dataset, 'test')

