#!/bin/bash

if [ -z "$1" ]
then
	echo "Please provide exactly 1 argument blackout amount"
else
	ratio=$1
	echo $ratio 
	name="fusion_ekf_blackout_"$ratio"_1"
	load_name = "fusion_ekf_blackout_"$ratio"_0"
	echo $name

	python train_ekf.py --data_size 1000 --batch 128 --epochs 10 \
	--experiment_name $name --pretrain 5 --blackout $ratio --train ekf \
	# add EKF checkpoint loading here!!!! :D 

 # 	python train_ekf.py --data_size 1000 --batch 128 --epochs 5 \
	# --experiment_name $name --pretrain 5 --blackout $ratio 
	# 	--init_state_noise 0.3 


	# python train_ekf.py --data_size 1000 --batch 128 --epochs 5 \
	# --experiment_name $name --pretrain 5 --blackout $ratio \
	#  	--init_state_noise 0.4 

fi 

