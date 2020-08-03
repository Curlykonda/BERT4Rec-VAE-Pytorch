#!/bin/bash
#SBATCH --job-name=bertje_nte_l
#SBATCH -n 4
#SBATCH -t 30:00:00
#SBATCH -p gpu_shared
#SBATCH --gres=gpu:2
#SBATCH --mem=60G

module load pre2019
module load Miniconda3/4.3.27
source activate thesis-user-modelling

python --version

#srun -n 2 -t 00:30:00 --pty bash -il

data=("./Data/DPG_nov19/100k_time_split_n_rnd_users/")
pt_news_enc="BERTje"
pt_news_enc_path="./BertModelsPT/bert-base-dutch-cased"

SEED=$SLURM_ARRAY_TASK_ID

art_len=30
neg_ratios=(49 74)

TEMP_EMBS=("nte" "ntev2") # "lte"
t_act_func="relu"

d_model=768

nie="lin_gelu"
LR=(1e-4)
n_epochs=50
#eval_seq_order="shuffle_exc_t"

n_users=100000
COUNTER=0
#################

exp_descr="100k_add" # _shuf_exc_t

for K in "${neg_ratios[@]}"
do
  for lr in "${LR[@]}"
  do
    for TE in "${TEMP_EMBS[@]}"
    do
      echo "$exp_descr $TE al$art_len k$K lr$lr s$SEED"
        #1
      CUDA_VISIBLE_DEVICES=0,1 python -u main.py --template train_bert_pcp --model_init_seed=$SEED --dataset_path=$data \
        --train_negative_sample_size=$K --pt_news_enc=$pt_news_enc --path_pt_news_enc=$pt_news_enc_path \
        --temp_embs=$TE --incl_time_stamp=1 --add_embs_func=add \
        --temp_embs_hidden_units 256 $d_model --temp_embs_act_func $t_act_func \
        --max_article_len=$art_len --nie_layer $nie --n_users=$n_users \
        --lr $lr --num_epochs=$n_epochs --cuda_launch_blocking=1 \
        --experiment_description $exp_descr $TE al$art_len k$K lr$lr s$SEED

      ((COUNTER++))
      echo "Exp counter: $COUNTER"
    done
  done
done