#!/bin/bash
#SBATCH --job-name=bertje_pe
#SBATCH -n 8
#SBATCH -t 08:00:00
#SBATCH -p gpu_shared
#SBATCH --mem=60000M


module load pre2019
module load Miniconda3/4.3.27
source activate thesis-user-modelling

python --version

#srun -n 2 -t 00:30:00 --pty bash -il

#data=("../Data/DPG_nov19/medium_time_split_most_common/")
#embeddings="../embeddings/cc.nl.300.bin"
pt_news_enc="BERTje"
pt_news_enc_path = "./BertModelsPT/bert-base-dutch-cased"

art_len=30
SEEDS=(113 42)
POS_EMBS=("tpe" "lpe")
method="last_cls"
N=0

nie="lin"
#LR=(0.01, 0.001, 0.0001)
lr=0.002
decay_step=25

exp_descr="pcp"

echo "$datapath"
for SEED in "${SEEDS[@]}"
do
  echo "$SEED"
  for POS in "${POS_EMBS[@]}"
  do
    #1
  python -u main.py --template train_bert_pcp --model_init_seed=$SEED \
  --pt_news_enc=$pt_news_enc --path_pt_news_enc=$pt_news_enc_path \
  --pos_embs=$POS --max_article_len=$art_len --bert_feature_method $method $N --nie_layer $nie \
  --lr $lr --decay_step $decay_step --cuda_launch_blocking=1 --device="cuda" \
  --experiment_description $exp_descr $POS s$SEED

    #2
  python -u main.py --template train_bert_pcp --model_init_seed=$SEED \
  --pt_news_enc=$pt_news_enc --path_pt_news_enc=$pt_news_enc_path \
  --pos_embs=$POS --max_article_len=$art_len --bert_feature_method $method $N --nie_layer $nie \
  --num_epochs=50 --bert_num_blocks=1 --bert_max_len=50 \
  --lr $lr --decay_step $decay_step --cuda_launch_blocking=1 --device="cuda" \
  --experiment_description $exp_descr $POS s$SEED

  done
done
wait


