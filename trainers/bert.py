from pathlib import Path
import numpy as np
import torch
import torch.nn as nn

from sklearn.preprocessing import OneHotEncoder
from torch.utils.tensorboard import SummaryWriter
from tqdm import tqdm

from .base import AbstractTrainer, MetricGraphPrinter, RecentModelLogger, BestModelLogger
from utils import AverageMeterSet
from .utils_metrics import calc_recalls_and_ndcgs_for_ks, calc_auc_and_mrr




class BERTTrainer(AbstractTrainer):
    def __init__(self, args, model, train_loader, val_loader, test_loader, export_root):
        super().__init__(args, model, train_loader, val_loader, test_loader, export_root)
        self.ce = nn.CrossEntropyLoss(ignore_index=0)

    @classmethod
    def code(cls):
        return 'bert'

    def add_extra_loggers(self):
        pass

    def log_extra_train_info(self, log_data):
        pass

    def log_extra_val_info(self, log_data):
        pass

    def calculate_loss(self, batch):
        seqs, labels = batch
        logits = self.model(seqs)  # B x T x V

        logits = logits.view(-1, logits.size(-1))  # (B*T) x V
        labels = labels.view(-1)  # B*T
        loss = self.ce(logits, labels)
        return loss

    def calculate_metrics(self, batch):
        seqs, candidates, labels = batch
        scores = self.model(seqs)  # B x T x V
        scores = scores[:, -1, :]  # B x V
        scores = scores.gather(1, candidates)  # B x C

        metrics = calc_recalls_and_ndcgs_for_ks(scores, labels, self.metric_ks)
        return metrics

class BERT4NewsCategoricalTrainer(BERTTrainer):
    def __init__(self, args, model, train_loader, val_loader, test_loader, export_root):

        super().__init__(args, model, train_loader, val_loader, test_loader, export_root)
        self.ce = nn.CrossEntropyLoss(reduction='mean')

    @classmethod
    def code(cls):
        return 'bert_news_ce'

    def calculate_loss(self, batch):

        cat_labels = batch['lbls']
        self.model.set_train_mode(True)
        # forward pass
        logits = self.model(cat_labels, **batch['input']) # L x N_c

        # categorical labels indicate which candidate is the correct one C = [0, N_c]
        # for positions where label is unequal -1
        lbls = cat_labels[cat_labels != -1]

        # calculate a separate loss for each class label per observation and sum the result.
        loss = self.ce(logits, lbls)

        ### calc metrics ###
        # one-hot encode lbls
        enc = OneHotEncoder(sparse=False)
        enc.fit(np.array(range(logits.shape[1])).reshape(-1, 1))
        oh_lbls = torch.LongTensor(enc.transform(lbls.cpu().reshape(len(lbls), 1)))
        scores = nn.functional.softmax(logits, dim=1)

        scores = scores.cpu().detach()

        metrics = calc_recalls_and_ndcgs_for_ks(scores, oh_lbls, self.metric_ks)
        metrics.update(calc_auc_and_mrr(scores, oh_lbls))

        return loss, metrics

    def calculate_metrics(self, batch):

        input = batch['input'].items()
        lbls = batch['lbls']
        self.model.set_train_mode(False)
        logits = self.model(None, **batch['input']) # (L x N_c)

        scores = nn.functional.softmax(logits, dim=1)

        # select scores for the article indices of candidates
        #scores = scores.gather(1, cands)  # (B x n_candidates)
        # labels: (B x N_c)
        metrics = calc_recalls_and_ndcgs_for_ks(scores, lbls, self.metric_ks)
        metrics.update(calc_auc_and_mrr(scores, lbls))

        return metrics

    def train_one_epoch(self, epoch, accum_iter):
        self.model.train()

        average_meter_set = AverageMeterSet()
        tqdm_dataloader = tqdm(self.train_loader)

        for batch_idx, batch in enumerate(tqdm_dataloader):

            batch = self.batch_to_device(batch)
            batch_size = self.args.train_batch_size

            # forward pass
            self.optimizer.zero_grad()
            loss, metrics_train = self.calculate_loss(batch)

            # backward pass
            loss.backward()
            self.optimizer.step()

            # update metrics
            average_meter_set.update('loss', loss.item())
            average_meter_set.update('lr', self.optimizer.defaults['lr'])

            for k, v in metrics_train.items():
                average_meter_set.update(k, v)

            tqdm_dataloader.set_description('Epoch {}, loss {:.3f} '.format(epoch + 1, average_meter_set['loss'].avg))
            accum_iter += batch_size

            if self._needs_to_log(accum_iter):
                tqdm_dataloader.set_description('Logging to Tensorboard')
                log_data = {
                    'state_dict': (self._create_state_dict()),
                    'epoch': epoch+1,
                    'accum_iter': accum_iter,
                }
                log_data.update(average_meter_set.averages())
                self.log_extra_train_info(log_data)
                self.logger_service.log_train(log_data)

            if self.args.local and batch_idx == 20:
                break

        # adapt learning rate
        if self.args.enable_lr_schedule:
            self.lr_scheduler.step()
            if epoch % self.lr_scheduler.step_size == 0:
                print(self.optimizer.defaults['lr'])


        return accum_iter

    def _create_loggers(self):
        root = Path(self.export_root)
        writer = SummaryWriter(root.joinpath('logs'))
        model_checkpoint = root.joinpath('models')

        train_loggers = [
            MetricGraphPrinter(writer, key='epoch', graph_name='Epoch', group_name='Train'),
            MetricGraphPrinter(writer, key='loss', graph_name='Loss', group_name='Train'),
            MetricGraphPrinter(writer, key='lr', graph_name='Learning Rate', group_name='Train'),
            MetricGraphPrinter(writer, key='AUC', graph_name='AUC', group_name='Train'),
            MetricGraphPrinter(writer, key='MRR', graph_name='MRR', group_name='Train')
        ]

        val_loggers = []
        for k in self.metric_ks:
            val_loggers.append(
                MetricGraphPrinter(writer, key='NDCG@%d' % k, graph_name='NDCG@%d' % k, group_name='Validation'))
            val_loggers.append(
                MetricGraphPrinter(writer, key='Recall@%d' % k, graph_name='Recall@%d' % k, group_name='Validation'))

            train_loggers.append(
                MetricGraphPrinter(writer, key='NDCG@%d' % k, graph_name='NDCG@%d' % k, group_name='Train'))
            train_loggers.append(
                MetricGraphPrinter(writer, key='Recall@%d' % k, graph_name='Recall@%d' % k, group_name='Validation'))


        val_loggers.append(MetricGraphPrinter(writer, key='AUC', graph_name='AUC', group_name='Validation'))
        val_loggers.append(MetricGraphPrinter(writer, key='MRR', graph_name='MRR', group_name='Validation'))

        val_loggers.append(RecentModelLogger(model_checkpoint))
        val_loggers.append(BestModelLogger(model_checkpoint, metric_key=self.best_metric))
        return writer, train_loggers, val_loggers



class Bert4NewsDistanceTrainer(BERTTrainer):
    def __init__(self, args, model, train_loader, val_loader, test_loader, export_root, dist_func='cos'):

        super().__init__(args, model, train_loader, val_loader, test_loader, export_root)

        self.dist_func_string = dist_func
        self.dist_func = None
        self.y_eval = False # indicates, if loss function requires additional target vector y
        self.loss_func = self.get_loss_func()


    @classmethod
    def code(cls):
        return 'bert_news_dist'

    def get_loss_func(self):
        if 'cos' == self.dist_func_string:
            # cos(x1, x2) = x1 * x2 / |x1|*|x2|  \in [-1, 1]
            # loss(x,y) = 1 - cos(x1,x2), if y==1
            # loss is zero when x1 = x2 -> cos = 1
            self.y_eval = True
            self.dist_func = nn.CosineSimilarity(dim=0, eps=1e-6)
            return nn.CosineEmbeddingLoss()
            #crit(x1.unsqueeze(1), x2.unsqueeze(1), y)
        elif 'mse' == self.dist_func_string:
            return nn.MSELoss()
        elif 'hinge' == self.dist_func_string:
            return nn.HingeEmbeddingLoss()
        elif 'mrank' == self.dist_func_string:
            nn.MarginRankingLoss()
        else:
            raise ValueError("{} is not a valid distance function!".format(self.dist_func))


    def calculate_loss(self, batch):
        seqs, mask, cands, labels = batch # (B x T)

        # cands = batch['cands'] # (B x L_m x N_cands)
        # labels = batch['lbls'] # (B x T)

        # select relevant candidates to reduce number of forward passes
        # (B x T x N_cands) -> (L_m x N_cands)
        rel_cands = cands[labels > 0]
        n_cands = cands.shape[2]

        # forward pass
        pred_embs, cand_embs = self.model(seqs, mask, rel_cands)
        # (B x T x D_a), (L_m x D_a)

        # gather relevant embedding for the masking positions
        # L_m := # of masked positions
        pred_embs = pred_embs[labels > 0]  # L_m x D_a
        pred_embs = pred_embs.unsqueeze(1).repeat(1, n_cands, 1) # repeat predicted embedding for n_cands

        # flatten
        cand_embs = cand_embs.view(-1, cand_embs.shape[-1]) # (L_m*N) x D_a
        pred_embs = pred_embs.view(-1, cand_embs.shape[-1]) # (L_m*N) x D_a
        labels = labels.view(-1)  # B*T

        # transpose
        # pred_embs = pred_embs.transpose(0, 1)
        # cand_embs = cand_embs.transpose(0, 1)

        assert pred_embs.size(0) == cand_embs.size(0)

        rel_labels = labels[labels > 0] # L_m
        #cand_labels := (B x T x N_c)
        # -> (L_m x N_c) -> (L_m * N_c)

        if self.y_eval:
            # construct target vector for distance loss
            # y==1 -> vectors should be similar
            # y==-1 -> vectors should be DIS-similar
            # y = (L_m x n_candidates)
            y = (-torch.ones_like(rel_cands))
            ## create mask that indicates, which candidate is the target
            mask = (rel_cands == rel_labels.unsqueeze(1).repeat(1, n_cands))
            y = y.masked_fill(mask, 1).view(-1)

            # compute distance loss
            # Maximise similarity betw. target & pred, while minimising pred and neg. samples
            # Note: CosineEmbeddingLoss 'prefers' vectors of shape (D_a x B) so perhaps transpose(0,1)
            # (L_m * N_c) x D_a
            loss = self.loss_func(pred_embs, cand_embs, y)
        else:
            loss = self.loss_func(pred_embs, cand_embs)

        return loss

    def calculate_metrics(self, batch):
        seqs, mask, cands, labels = batch
        # seqs, mask = batch['input']  # (B x T)
        # cands = batch['cands']  # (B x N_cands)
        # labels = batch['lbls']  # (B x T)
        n_cands = cands.shape[1]

        # forward pass
        pred_embs, cand_embs = self.model(seqs, mask, cands)

        # select masking position
        pred_embs = pred_embs[:, -1, :] # # (B x L_hist x D_a) -> (B x D_a)
        pred_embs = pred_embs.unsqueeze(1).repeat(1, n_cands, 1) # repeat predicted embedding for n_cands

        # flatten
        cand_embs = cand_embs.view(-1, cand_embs.shape[-1]) # (B*N) x D_a
        pred_embs = pred_embs.view(-1, cand_embs.shape[-1]) # (B*N) x D_a

        # transpose
        pred_embs = pred_embs.transpose(0, 1)
        cand_embs = cand_embs.transpose(0, 1)

        # compute distance scores
        with torch.no_grad():
            #y = torch.ones(cand_embs.size(0), cand_embs.size(1))
            # note that the loss internally applies 'mean' reduction so we need simple distance fucntion
            dist_scores = self.dist_func(pred_embs, cand_embs)

        # Note: inside this function, scores are inverted. check if aligns with distance function
        metrics = calc_recalls_and_ndcgs_for_ks(dist_scores.view(-1, n_cands), labels.view(-1, n_cands), self.metric_ks)
        metrics.update(calc_auc_and_mrr(dist_scores.view(-1, n_cands), labels.view(-1, n_cands)))
        return metrics