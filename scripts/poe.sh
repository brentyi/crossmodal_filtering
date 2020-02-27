#!/bin/bash

python train_fusion.py --data_size 1000 --batch 128 --epochs 5 --fusion_type poe \
--experiment_name fusion_poe_final_0 --pretrain 5 \
--train fusion --load_checkpoint checkpoints/fusion_poe_1000_hu64_1loss-phase_3_e2e.ckpt --lr 1e-5 \
--init_state_noise 0.3 



python train_fusion.py --data_size 1000 --batch 128 --epochs 5 --fusion_type weighted \
--experiment_name fusion_poe_final_0 --pretrain 5 \
--train fusion  --lr 1e-5  --init_state_noise 0.4 

