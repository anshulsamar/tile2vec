# run.py
# =============================================================================
# Original code by Neal Jean/Sherrie Wang (see example 2 notebook in tile2vec
# repo). Edits and extensions by Anshul Samar. 

import sys
tile2vec_dir = '/home/asamar/tile2vec'
sys.path.append('../')
sys.path.append(tile2vec_dir)

import os
import torch
from torch import optim
from time import time
import random
import numpy as np
from fig_utils import *
from src.datasets import triplet_dataloader
from src.training import train_model, validate_model, prep_triplets
from utils import *
import paths
from tensorboardX import SummaryWriter
import argparse
import pickle

# Parse command line arguments
parser = argparse.ArgumentParser()

# Training
parser.add_argument('-train', action='store_true')
parser.add_argument('--ntrain', dest='ntrain', type=int, default=100000)
parser.add_argument('-lsms_train',  action='store_true')
parser.add_argument('--nlsms_train', dest='nlsms_train', type=int,
                    default=100000)

# Testing
parser.add_argument('-test',  action='store_true')
parser.add_argument('--ntest', dest='ntest', type=int, default=50000)
parser.add_argument('-lsms_val',  action='store_true')
parser.add_argument('--nlsms_val', dest='nlsms_val', type=int, default=50000)
parser.add_argument('-val',  action='store_true')
parser.add_argument('--nval', dest='nval', type=int, default=50000)

# Regression
parser.add_argument('-predict_small', action='store_true')
parser.add_argument('-predict_big', action='store_true')
parser.add_argument('-quantile', action='store_true')
parser.add_argument('--trials', dest="trials", type=int, default=10)

# Model
parser.add_argument('--model', dest="model", default="tilenet")
parser.add_argument('--z_dim', dest="z_dim", type=int, default=512)
parser.add_argument('--model_fn', dest='model_fn')
parser.add_argument('--exp_name', dest='exp_name')
parser.add_argument('--epochs_end', dest="epochs_end", type=int, default=50)
parser.add_argument('--epochs_start', dest="epochs_start", type=int, default=0)
parser.add_argument('-save_models', action='store_true')
parser.add_argument('--gpu', dest="gpu", type=int, default=0)

# Debug
parser.add_argument('-debug', action='store_true')

args = parser.parse_args()
print(args)


# Load Model Definition
if args.model == "minires":
    from src.minires import make_tilenet
elif args.model == "miniminires":
    from src.miniminires import make_tilenet
else:
    from src.tilenet import make_tilenet

if not args.save_models:
    print("Not Saving Checkpoints")

# Environment
os.environ["CUDA_DEVICE_ORDER"] = "PCI_BUS_ID"
os.environ['CUDA_VISIBLE_DEVICES'] = str(args.gpu)
cuda = torch.cuda.is_available()
if args.debug:
    torch.manual_seed(1)
    if cuda:
        # Not tested if this works/see pytorch thread it may not
        torch.cuda.manual_seed_all(1)
        torch.backends.cudnn.deterministic = True

# Logging
writer = SummaryWriter(paths.log_dir + args.exp_name)
    
# Data Parameters
img_type = 'landsat'
bands = 5
augment = True
batch_size = 50
shuffle = True
num_workers = 4

if args.train:
    train_dataloader = triplet_dataloader(img_type, paths.train_tiles,
                                          bands=bands, augment=augment,
                                          batch_size=batch_size,
                                          shuffle=shuffle,
                                          num_workers=num_workers,
                                          n_triplets=args.ntrain,
                                          pairs_only=True)

    print('Train Dataloader set up complete.')

if args.test:
    test_dataloader = triplet_dataloader(img_type, paths.test_tiles,
                                         bands=bands, augment=augment,
                                         batch_size=batch_size,
                                         shuffle=shuffle,
                                         num_workers=num_workers,
                                         n_triplets=args.ntest,
                                         pairs_only=True)

    print('Test Dataloader set up complete.')

if args.val:
    val_dataloader = triplet_dataloader(img_type, paths.val_tiles,
                                         bands=bands, augment=augment,
                                         batch_size=batch_size,
                                         shuffle=shuffle,
                                         num_workers=num_workers,
                                         n_triplets=args.nval,
                                         pairs_only=True)

    print('Val Dataloader set up complete.')

if args.lsms_train:
    lsms_train_dataloader = triplet_dataloader(img_type, paths.lsms_train_tiles,
                                         bands=bands, augment=augment,
                                         batch_size=batch_size,
                                         shuffle=shuffle,
                                         num_workers=num_workers,
                                         n_triplets=args.nlsms_train,
                                         pairs_only=True)

    print('LSMS Dataloader set up complete.')

if args.lsms_val:
    lsms_val_dataloader = triplet_dataloader(img_type, paths.lsms_val_tiles,
                                         bands=bands, augment=augment,
                                         batch_size=batch_size,
                                         shuffle=shuffle,
                                         num_workers=num_workers,
                                         n_triplets=args.nlsms_val,
                                         pairs_only=True)

    print('LSMS Val Dataloader set up complete.')
   
# Training Parameters
in_channels = bands
TileNet = make_tilenet(in_channels=in_channels, z_dim=args.z_dim)
if cuda: TileNet.cuda()

# Load saved model
if args.model_fn:
    TileNet.load_state_dict(torch.load(args.model_fn))

print('TileNet set up complete.')

lr = 1e-3
optimizer = optim.Adam(TileNet.parameters(), lr=lr, betas=(0.5, 0.999))
margin = 50
l2 = 0.01
print_every = 10000

# Directory to save model params
if not os.path.exists(paths.model_dir): os.makedirs(paths.model_dir)
if not os.path.exists(paths.model_dir + args.exp_name):
    os.makedirs(paths.model_dir + args.exp_name)
    

# Regression variables
lsms = True
test_imgs = 642
patches_per_img = 10
country = 'uganda'
country_path = paths.lsms_data
dimension = None
k = 5
k_inner = 5
points = 10
alpha_low = 1
alpha_high = 5
regression_margin = 0.25

# Statistics
train_loss = []
test_loss = []
lsms_loss_train = []
lsms_loss_val = []
val_loss = []
r2_list = {'big':{},'small':{}}
mse_list = {'big':{},'small':{}}
save_dir = paths.model_dir + args.exp_name + '/'

t0 = time()

with open(save_dir + 'command.p','wb') as f:
    pickle.dump(args, f)

# Train
print('Begin Training')
for epoch in range(args.epochs_start, args.epochs_end):
    if args.train:
        avg_loss_train = train_model(TileNet, cuda, train_dataloader, optimizer,
                                     epoch+1, margin=margin, l2=l2,
                                     print_every=print_every, t0=t0)
        train_loss.append(avg_loss_train)
        writer.add_scalar('loss/train',avg_loss_train, epoch)

    if args.lsms_train:
        avg_loss_lsms_train = train_model(TileNet, cuda, lsms_train_dataloader,
                                          optimizer, epoch+1, margin=margin,
                                          l2=l2, print_every=print_every, t0=t0)
        lsms_loss_train.append(avg_loss_lsms_train)
        writer.add_scalar('loss/lsms_train',avg_loss_lsms_train, epoch)

    if args.test:
        avg_loss_test= validate_model(TileNet, cuda, test_dataloader, optimizer,
                                      epoch+1, margin=margin, l2=l2,
                                      print_every=print_every, t0=t0)
        test_loss.append(avg_loss_test)
        writer.add_scalar('loss/test',avg_loss_test, epoch)
        
    if args.val:
        avg_loss_val= validate_model(TileNet, cuda, val_dataloader, optimizer,
                                      epoch+1, margin=margin, l2=l2,
                                      print_every=print_every, t0=t0)
        val_loss.append(avg_loss_val)
        writer.add_scalar('loss/val',avg_loss_val, epoch)

    if args.lsms_val:
        avg_loss_lsms_val = validate_model(TileNet, cuda, lsms_val_dataloader,
                                           optimizer, epoch+1, margin=margin,
                                           l2=l2, print_every=print_every, t0=t0)
        lsms_loss_val.append(avg_loss_lsms_val)
        writer.add_scalar('loss/lsms_val',avg_loss_lsms_val, epoch)
        
    if args.predict_small:
        epoch_idx = epoch - args.epochs_start
        # Small Image Features
        print("Generating LSMS Small Features")
        img_names = [paths.lsms_images_small + 'landsat7_uganda_3yr_cluster_' \
                     + str(i) + '.tif' for i in range(test_imgs)]
        X = get_small_features(img_names, TileNet, args.z_dim, cuda, bands,
                               patch_size=50, patch_per_img=10, save=True,
                               verbose=False, npy=False, quantile=args.quantile)
        np.save(paths.lsms_data + 'cluster_conv_features_' + args.exp_name +\
                '.npy', X)

        r2_list['small'][epoch_idx] = []
        mse_list['small'][epoch_idx] = []
        for i in range(args.trials):
            X, y, y_hat, r2, mse = predict_consumption(country, country_path,
                                                       dimension, k, k_inner,
                                                       points, alpha_low,
                                                       alpha_high,
                                                       regression_margin,
                                                       exp=args.exp_name)

            r2_list['small'][epoch_idx].append(r2)
            mse_list['small'][epoch_idx].append(mse)

        mean_r2 = np.mean(r2_list['small'][epoch_idx])
        mean_mse = np.mean(mse_list['small'][epoch_idx])
        with open(save_dir + '/y_small_e' + str(epoch) + '.p', 'wb') as f:
            pickle.dump((y, y_hat, mean_r2),f)
        print("Small r2: " + str(mean_r2))
        print("Small mse: " + str(mean_mse))
        writer.add_scalar('r2',mean_r2, epoch)
        writer.add_scalar('mse',mean_mse, epoch)
        
    if args.predict_big:
        # Big Image Features
        epoch_idx = epoch - args.epochs_start
        print("Generating LSMS Big Image Features")
        img_names = [paths.lsms_images_big + 'landsat7_uganda_3yr_cluster_' \
                     + str(i) + '.tif' for i in range(test_imgs)]
        X = get_big_features(img_names, TileNet, args.z_dim, cuda, bands,
                             patch_size=50, patch_per_img=10, save=True,
                             verbose=False, npy=False, quantile=args.quantile)
        np.save(paths.lsms_data + 'cluster_conv_features_' + args.exp_name +\
                '.npy', X)

        r2_list['big'][epoch_idx] = []
        mse_list['big'][epoch_idx] = []
        for i in range(args.trials):
            X, y, y_hat, r2, mse = predict_consumption(country, country_path,
                                                       dimension, k, k_inner,
                                                       points, alpha_low,
                                                       alpha_high,
                                                       regression_margin,
                                                       exp=args.exp_name)

            r2_list['big'][epoch].append(r2)
            mse_list['big'][epoch].append(mse)

        mean_r2 = np.mean(r2_list['big'][epoch_idx])
        mean_mse = np.mean(mse_list['big'][epoch_idx])
        with open(save_dir + '/y_big_e' + str(epoch) + '.p', 'wb') as f:
            pickle.dump((y, y_hat, mean_r2),f)
        print("Big r2: " + str(mean_r2))
        print("Big mse: " + str(mean_mse))
        writer.add_scalar('r2',mean_r2, epoch)
        writer.add_scalar('mse',mean_mse, epoch)

    if args.save_models:
        print("Saving")
        save_name = 'TileNet' + str(epoch) + '.ckpt'
        model_path = os.path.join(save_dir, save_name)
        torch.save(TileNet.state_dict(), model_path)
        if args.train:
            with open(save_dir + '/train_loss.p', 'wb') as f:
                pickle.dump(train_loss, f)
        if args.test:
            with open(save_dir + '/test_loss.p', 'wb') as f:
                pickle.dump(test_loss, f)
        if args.lsms_train:
            with open(save_dir + '/lsms_loss_train.p', 'wb') as f:
                pickle.dump(lsms_loss_train, f)
        if args.lsms_val:
            with open(save_dir + '/lsms_loss_val.p', 'wb') as f:
                pickle.dump(lsms_loss_val, f)
        if args.predict_big or args.predict_small:
            with open(save_dir + '/r2_' + str(epoch) + '.p', 'wb') as f:
                pickle.dump(r2_list, f)
            with open(save_dir + '/mse_' + str(epoch) + '.p', 'wb') as f:
                pickle.dump(mse_list, f)
        
print("Finished.")

    


    
