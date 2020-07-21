#!/bin/bash
#SBATCH --job-name=test_mul_gpu
#SBATCH -n 8
#SBATCH -t 2:00:00
#SBATCH -p gpu_shared
#SBATCH --gres=gpu:2
#SBATCH --mem=60000M


module load pre2019
module load Miniconda3/4.3.27
source activate thesis-user-modelling

python --version

data=("./Data/DPG_nov19/100k_time_split_n_rnd_users/")
w_emb="./pc_word_embeddings/cc.nl.300.bin"

SEED=42

art_len=30
add_emb_size=400
POS_EMBS=("lpe") #
neg_ratios=(4 24) # 9 24

enc="wucnn"
d_art=400

n_bert_layers=2

nie="lin_gelu"

lr=1e-3
n_epochs=10
n_gpu=2

n_users=100000
exp_descr="100k_NpaCNN_cat"
COUNTER=0

echo "$data"
echo "$exp_descr"

echo "$SEED"
for K in "${neg_ratios[@]}"
do
  for POS in "${POS_EMBS[@]}"
  do

    echo "$exp_descr $POS al$art_len k$K nl$n_bert_layers lr$lr s$SEED"
      #1
    python -u main.py --template train_bert_pcp --model_init_seed=$SEED --dataset_path=$data \
    --bert_num_blocks=$n_bert_layers --train_negative_sampler_code random --train_negative_sample_size=$K \
    --num_gpu=$n_gpu --add_embs_func=concat --add_emb_size=$add_emb_size \
    --news_encoder $enc --dim_art_emb $d_art  --pt_word_emb_path=$w_emb --lower_case=1 \
    --pos_embs=$POS --max_article_len=$art_len --nie_layer=$nie --n_users=$n_users \
    --lr $lr --num_epochs=$n_epochs --cuda_launch_blocking=1 \
    --experiment_description $exp_descr $POS al$art_len k$K lr$lr s$SEED

    ((COUNTER++))
    echo "Exp counter: $COUNTER"

  done
done