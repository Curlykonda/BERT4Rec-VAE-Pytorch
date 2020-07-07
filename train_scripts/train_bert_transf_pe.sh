#!/bin/bash
#SBATCH --job-name=transf_pe
#SBATCH -n 8
#SBATCH -t 1:00:00
#SBATCH -p gpu_short
#SBATCH --mem=60000M


module load pre2019
module load Miniconda3/4.3.27
source activate thesis-user-modelling

python --version

#srun -n 2 -t 00:30:00 --pty bash -il

data=("./Data/DPG_nov19/40k_time_split_n_rnd_users/")
w_emb="./pc_word_embeddings/cc.nl.300.bin"
#pt_news_enc="./BertModelsPT/bert-base-dutch-cased"
art_len=30
SEED=42
POS_EMBS=("tpe" "lpe")
neg_ratios=(4 24 49 99)

enc="transf"
neg_sampler="random"

nie="lin"
#LR=(0.01, 0.001, 0.0001)
lr=0.001

n_users=40000
exp_descr="40k_transf"
COUNTER=0

echo "$data"
echo "$exp_descr"

echo "$SEED"
for POS in "${POS_EMBS[@]}"
do
  for K in "${neg_ratios[@]}"
  do

    echo "$exp_descr $POS al$art_len k$K s$SEED neg $neg_sampler"
      #1
    python -u main.py --template train_bert_pcp --model_init_seed=$SEED --dataset_path=$data \
    --train_negative_sampler_code random --train_negative_sample_size=$K \
    --news_encoder $enc --dim_art_emb $d_art  --pt_word_emb_path=$w_emb --lower_case=1 \
    --pos_embs=$POS --max_article_len=$art_len --nie_layer=$nie --n_users=$n_users \
    --lr $lr --cuda_launch_blocking=1 \
    --experiment_description $exp_descr $POS al$art_len k$K s$SEED

    ((COUNTER++))
    echo "Exp counter: $COUNTER"

  done
done


#  echo "max hist len 50"
#    #2
#  python -u main.py --template train_bert_pcp --model_init_seed=$SEED \
#  --news_encoder $enc --dim_art_emb $d_art  --pt_word_emb_path=$w_emb --lower_case=1 \
#  --num_epochs=100 --bert_num_blocks=2 --max_hist_len=50 \
#  --pos_embs=$POS --max_article_len=$art_len --nie_layer $nie \
#  --lr $lr --decay_step $decay_step --cuda_launch_blocking=1 --train_batch_size=$batch \
#  --experiment_description $exp_descr $POS l$art_len s$SEED
#
#  echo "bert blocks 1"
#    #3
#  python -u main.py --template train_bert_pcp --model_init_seed=$SEED \
#  --news_encoder $enc --dim_art_emb $d_art  --pt_word_emb_path=$w_emb --lower_case=1 \
#  --num_epochs=100 --bert_num_blocks=1 --max_hist_len=100 \
#  --pos_embs=$POS --max_article_len=$art_len --nie_layer $nie \
#  --lr $lr --decay_step $decay_step --cuda_launch_blocking=1 --train_batch_size=$batch \
#  --experiment_description $exp_descr $POS l$art_len s$SEED
#
#  done