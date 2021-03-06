# author : Maelig Jacquet
# June 2020
# adapted from davidsanberg/facenet

"""Performs face alignment and calculates L2 distance between the embeddings of images from 2 folders."""

# MIT License
#
# Copyright (c) 2016 David Sandberg
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

from scipy import misc
import tensorflow as tf
import numpy as np
import sys
import os
import copy
import argparse
import facenet
import align.detect_face
import xlsxwriter
import itertools
import cv2
from tqdm import tqdm
#import imageio

parser = argparse.ArgumentParser()


parser.add_argument('image_files', type=str, nargs='+', help='Images to compare')
parser.add_argument('--image_size', type=int,
    help='Image size (height, width) in pixels.', default=160)
parser.add_argument('--margin', type=int,
    help='Margin for the crop around the bounding box (height, width) in pixels.', default=44)
parser.add_argument('--gpu_memory_fraction', type=float,
    help='Upper bound on the amount of GPU memory that will be used by the process.', default=0.01)
parser.add_argument('--a_same', type=float,
    help='Scale parameter (a) for Weibull, same person.', default=0.796174014389305)
parser.add_argument('--b_same', type=float,
    help='Shape parameter (b) for Weibull, same person.', default=3.750398608516835)
parser.add_argument('--a_different', type=float,
    help='Scale parameter (a) for Weibull, different person.', default=1.405668708882522)
parser.add_argument('--b_different', type=float,
    help='Shape parameter (b) for Weibull, different person.', default=12.478248305735089)
parser.add_argument('--model', type=str,
    help='Could be either a directory containing the meta_file and ckpt_file or a model protobuf (.pb) file', default='../data/model/20180402-114759.pb')
parser.add_argument('out_file', type=str,
    help='Output file.', default='../output/results.csv')

args = parser.parse_args()

a_same = args.a_same
a_different = args.a_different
b_same = args.b_same
b_different = args.b_different
outfile = args.out_file

dirimg1 = args.image_files[0]
dirimg2 = args.image_files[1]

if os.path.isdir(dirimg1):
    listimg1 = []
    for f in os.listdir(dirimg1):
        listimg1.append(dirimg1 + "/" + f )
else :
    listimg1=[dirimg1]


if os.path.isdir(dirimg2):
    listimg2 = []
    for f in os.listdir(dirimg2):
        listimg2.append(dirimg2 + "/" + f )
else :
    listimg2=[dirimg2]


def main(listimg1, listimg2):
    with tf.Graph().as_default():

        with tf.Session() as sess:

            # Load the model
            facenet.load_model(args.model)

            # Get input and output tensors
            images_placeholder = tf.get_default_graph().get_tensor_by_name("input:0")
            embeddings = tf.get_default_graph().get_tensor_by_name("embeddings:0")
            phase_train_placeholder = tf.get_default_graph().get_tensor_by_name("phase_train:0")

            # Run forward pass to calculate embeddings
            ###### original compare.py modif
            nrof_traces = len(listimg1)
            nrof_bdd = len(listimg2)

            emb1 = np.array([])
            emb2 = np.array([])

            feed_dict1 = { images_placeholder: images1, phase_train_placeholder:False }
            emb1 = sess.run(embeddings, feed_dict=feed_dict1)

            feed_dict2 = { images_placeholder: images2, phase_train_placeholder:False }
            emb2 = sess.run(embeddings, feed_dict=feed_dict2)

            print (nrof_traces, "images in folder 1")
            print (nrof_bdd, "images in folder 2")
            print (nrof_traces * nrof_bdd, "comparisons to run")

            # Create output folder if doesnt exist
            out_path = os.path.dirname(outfile)
            if not os.path.exists(out_path):
                os.makedirs(out_path)

            outf = open(outfile, "w+")
            outf.write("Image 1;Image 2;Score\n")

            print ('MATCHING...')

            for (i, a) in zip(range(len(images1)), listimg1):
                nom_img1 = os.path.basename(a)
                for (j, b) in zip(range(len(images2)), listimg2):
                    nom_img2 = os.path.basename(b)
                    dist = np.sqrt(np.sum(np.square(np.subtract(emb1[i,:], emb2[j,:]))))

                    outf.write("%s;%s;%.3f\n" % (nom_img1, nom_img2, dist))

            outf.close()


            print ('END')


def load_and_align_data(image_paths, image_size, margin, gpu_memory_fraction):

    minsize = 20 # minimum size of face
    threshold = [ 0.6, 0.7, 0.7 ]  # three steps's threshold
    factor = 0.709 # scale factor


    images1 = []
    images2 = []

    print('Creating networks and loading parameters for :', (os.path.basename(os.path.dirname(image_paths[0]))))
    with tf.Graph().as_default():
        gpu_options = tf.GPUOptions(per_process_gpu_memory_fraction=gpu_memory_fraction)
        sess = tf.Session(config=tf.ConfigProto(gpu_options=gpu_options, log_device_placement=False))
        with sess.as_default():
            pnet, rnet, onet = align.detect_face.create_mtcnn(sess, None)

    with tqdm(total=len(image_paths), desc = 'Loading and aligning images from %s' % (os.path.basename(os.path.dirname(image_paths[0])))) as pbar2:
        img_list = []
        for image in image_paths:
            img = misc.imread(os.path.expanduser(image), mode='RGB')

            img_size = np.asarray(img.shape)[0:2]
            bounding_boxes, _ = align.detect_face.detect_face(img, minsize, pnet, rnet, onet, threshold, factor)
            if len(bounding_boxes) < 1:
            # image_paths.remove(image)
                print("can't detect face, remove ", image)
                if image in image_paths:
                    image_paths.remove(image)
                continue
            det = np.squeeze(bounding_boxes[0,0:4])
            bb = np.zeros(4, dtype=np.int32)
            bb[0] = np.maximum(det[0]-margin/2, 0)
            bb[1] = np.maximum(det[1]-margin/2, 0)
            bb[2] = np.minimum(det[2]+margin/2, img_size[1])
            bb[3] = np.minimum(det[3]+margin/2, img_size[0])
            cropped = img[bb[1]:bb[3],bb[0]:bb[2],:]
            aligned = misc.imresize(cropped, (image_size, image_size), interp='bilinear')
            prewhitened = facenet.prewhiten(aligned)

            img_list.append(prewhitened)
            pbar2.update(1)

            if image_paths == listimg1:
                images1 = np.stack(img_list)

            elif image_paths == listimg2:
                images2 = np.stack(img_list)

        return images1 if image_paths == listimg1 else images2


images1= load_and_align_data(listimg1, args.image_size, args.margin, args.gpu_memory_fraction)
images2= load_and_align_data(listimg2, args.image_size, args.margin, args.gpu_memory_fraction)

main(listimg1, listimg2)

# if __name__ == '__main__':
#     main(parse_arguments(sys.argv[1:]))
# print (sys.argv)
