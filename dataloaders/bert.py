import itertools

from .base import AbstractDataloader
from .negative_samplers import negative_sampler_factory

import torch
import torch.utils.data as data_utils

class BertDataloader(AbstractDataloader):
    def __init__(self, args, dataset):
        super().__init__(args, dataset)

        args.num_items = len(self.smap)
        self.max_hist_len = args.bert_max_len
        self.mask_prob = args.bert_mask_prob

        self.mask_token = self.item_count + 1 ## item_count = len(self.smap)
        args.bert_mask_token = self.mask_token

        self.split_method = args.split
        self.multiple_eval_items = args.split == "time_threshold"
        self.valid_items = self.get_valid_items()

        # self.vocab = dataset['vocab']
        # self.art_idx2word_ids = dataset['art2words']

        ####################
        # Negative Sampling

        self.train_negative_samples = self.create_neg_samples(args.train_negative_sampler_code,
                                                                args.train_negative_sample_size,
                                                                args.train_negative_sampling_seed,
                                                                self.valid_items['train'])

        self.test_negative_samples = self.create_neg_samples(args.test_negative_sampler_code,
                                                                args.test_negative_sample_size,
                                                                args.test_negative_sampling_seed,
                                                                self.valid_items['test'])
    @classmethod
    def code(cls):
        return 'bert'

    def get_pytorch_dataloaders(self):
        train_loader = self._get_train_loader()
        val_loader = self._get_val_loader()
        test_loader = self._get_test_loader()
        return train_loader, val_loader, test_loader

    def _get_train_loader(self):
        dataset = self._get_train_dataset()
        dataloader = data_utils.DataLoader(dataset, batch_size=self.args.train_batch_size,
                                           shuffle=True, pin_memory=True)
        return dataloader

    def _get_train_dataset(self):
        dataset = BertTrainDataset(self.train, self.art_idx2word_ids, self.max_hist_len, self.mask_prob, self.mask_token, self.item_count, self.rng)
        return dataset

    def _get_val_loader(self):
        return self._get_eval_loader(mode='val')

    def _get_test_loader(self):
        return self._get_eval_loader(mode='test')

    def _get_eval_loader(self, mode):
        batch_size = self.args.val_batch_size if mode == 'val' else self.args.test_batch_size
        dataset = self._get_eval_dataset(mode)
        dataloader = data_utils.DataLoader(dataset, batch_size=batch_size,
                                           shuffle=False, pin_memory=True)
        return dataloader

    def _get_eval_dataset(self, mode):
        targets = self.val if mode == 'val' else self.test
        dataset = BertEvalDataset(self.train, targets, self.art_idx2word_ids, self.max_hist_len, self.mask_token, self.test_negative_samples, self.multiple_eval_items)
        return dataset

    def create_neg_samples(self, code, neg_sample_size, seed, item_set):
        if self.split_method != "time_threshold":
            # use item counts for simple neg sampling

            negative_sampler = negative_sampler_factory(code, self.train, self.val, self.test,
                                                              self.user_count, item_set,
                                                              neg_sample_size,
                                                              seed,
                                                              self.save_folder)
        else:
            # use distinguished set for neg sampling
            raise NotImplementedError()
            # negative_sampler = negative_sampler_factory(code, self.train, self.val, self.test,
            #                                                   self.user_count, self.item_count,
            #                                                   neg_sample_size,
            #                                                   seed,
            #                                                   self.save_folder)


        return negative_sampler.get_negative_samples()

    def get_valid_items(self):
        all_items = set(self.smap.values()) # train + test + val
        if self.mask_token in all_items:
            all_items.remove(self.mask_token)

        if self.split_method != "time_threshold":
            test = train = all_items
        else:
            train = set(itertools.chain.from_iterable(self.train.values()))
            test = all_items

        return {'train': list(train), 'test': list(test)}


class BertDataloaderNews(BertDataloader):
    def __init__(self, args, dataset):
        super(BertDataloaderNews, self).__init__(args, dataset)

        dataset = dataset.load_dataset()
        self.vocab = dataset['vocab']
        self.art_index2word_ids = dataset['art2words'] # art ID -> [word IDs]

        #self.CLOZE_MASK_TOKEN = 0

        # create direct mapping art_id -> word_ids
        self.art_id2word_ids = {art_idx: self.art_index2word_ids[art_id] for art_id, art_idx in self.smap.items()}
        del self.art_index2word_ids

    @classmethod
    def code(cls):
        return 'bert_news'

    def _get_train_dataset(self):
        dataset = BertTrainDatasetNews(self.train, self.art_id2word_ids, self.max_hist_len, self.mask_prob, self.mask_token, self.item_count, self.rng)
        return dataset

    def _get_eval_dataset(self, mode):
        targets = self.val if mode == 'val' else self.test
        dataset = BertEvalDatasetNews(self.train, targets, self.art_id2word_ids, self.max_hist_len, self.mask_token, self.test_negative_samples, multiple_eval_items=self.multiple_eval_items)
        return dataset

def art_idx2word_ids(art_idx, mapping):
    if mapping is not None:
        return mapping[art_idx]
    else:
        return art_idx

class BertTrainDataset(data_utils.Dataset):
    def __init__(self, u2seq, max_len, mask_prob, mask_token, num_items, rng, pad_token=0,):
        self.u2seq = u2seq
        self.users = sorted(self.u2seq.keys())
        self.max_len = max_len
        self.mask_prob = mask_prob
        self.mask_token = mask_token
        self.pad_token = pad_token
        self.num_items = num_items
        self.rng = rng

    def __len__(self):
        return len(self.users)

    def __getitem__(self, index):

        # generate masked item sequence on-the-fly
        user = self.users[index]
        seq = self._getseq(user)

        tokens, labels = self.gen_masked_seq(seq)

        tokens = tokens[-self.max_len:]
        labels = labels[-self.max_len:]

        mask_len = self.max_len - len(tokens)

        # mask token are also append to the left if sequence needs padding
        # Why not uses separate padding token? how does model know when to predict for an actual masked off item?
        tokens = [0] * mask_len + tokens
        labels = [0] * mask_len + labels

        return torch.LongTensor(tokens), torch.LongTensor(labels)

    def _getseq(self, user):
        return self.u2seq[user]

    def gen_masked_seq(self, seq):
        tokens = []
        labels = []

        for s in seq:
            prob = self.rng.random()
            if prob < self.mask_prob:
                prob /= self.mask_prob

                if prob < 0.8:
                    tokens.append(self.mask_token)
                elif prob < 0.9:
                    tokens.append(self.rng.randint(1, self.num_items))
                else:
                    tokens.append(s)

                labels.append(s)
            else:
                tokens.append(s)
                labels.append(0)

        return tokens, labels


class BertTrainDatasetNews(BertTrainDataset):
    def __init__(self, u2seq, art2words, max_len, mask_prob, mask_token, num_items, rng):
        super(BertTrainDatasetNews, self).__init__(u2seq, max_len, mask_prob, mask_token, num_items, rng)

        self.art2words = art2words

    def gen_masked_seq(self, seq):
        tokens = []
        labels = []
        for s in seq:
            prob = self.rng.random()
            if prob < self.mask_prob:
                prob /= self.mask_prob

                if prob < 0.8:
                    tokens.append(self.mask_token)
                elif prob < 0.9:
                    tokens.append(art_idx2word_ids(self.rng.randint(1, self.num_items), self.art2words))
                else:
                    tokens.append(art_idx2word_ids(s, self.art2words))

                labels.append(s)
            else:
                tokens.append(art_idx2word_ids(s, self.art2words))
                labels.append(0)

        return tokens, labels


class BertEvalDataset(data_utils.Dataset):
    def __init__(self, u2seq, u2answer, max_hist_len, mask_token, negative_samples, pad_token=0, multiple_eval_items=True):
        self.u2hist = u2seq
        self.u_sample_ids = sorted(self.u2hist.keys())
        self.u2targets = u2answer
        #self.art2words = art2words
        self.max_hist_len = max_hist_len
        self.mask_token = mask_token
        self.pad_token = pad_token
        self.negative_samples = negative_samples

        self.mul_eval_items = multiple_eval_items

        if self.mul_eval_items:
            u2hist_ext = {}
            u2targets_ext = {}
            for u in self.u_sample_ids:
                hist = self.u2hist[u]
                for i, item in enumerate(self.u2targets[u]):
                    u_ext = self.concat_ints(u, i) # extend user id with item enumerator
                    target = item
                    u2hist_ext[u_ext] = hist
                    u2targets_ext[u_ext] = target
                    hist.append(item)

            self.u_sample_ids = list(u2hist_ext.keys())
            self.u2hist = u2hist_ext
            self.u2targets = u2targets_ext

    def __len__(self):
        return len(self.u_sample_ids)

    def __getitem__(self, index):
        user = self.u_sample_ids[index]
        seq = self.u2hist[user]
        target = self.u2targets[user]

        if target == []:
            return
        else:
            if isinstance(user, str):
                negs = self.negative_samples[int(user[:-1])]
            else:
                negs = self.negative_samples[user] # get negative samples
            return self.gen_eval_instance(seq, target, negs)

        # negs = self.negative_samples[user]
        #
        # candidates = target + negs
        # labels = [1] * len(target) + [0] * len(negs)
        #
        # seq = seq + [self.mask_token] # model can only predict the next
        # seq = seq[-self.max_len:]
        # padding_len = self.max_len - len(seq)
        # seq = [0] * padding_len + seq
        #
        # return torch.LongTensor(seq), torch.LongTensor(candidates), torch.LongTensor(labels)

    def gen_eval_instance(self, hist, target, negs):
        candidates = target + negs
        #candidates = [art_idx2word_ids(cand, self.art2words) for cand in candidates]
        labels = [1] * len(target) + [0] * len(negs)

        hist = hist + [self.mask_token]  # predict only the next/last token in seq
        hist = hist[-self.max_hist_len:]
        padding_len = self.max_hist_len - len(hist)
        hist = [self.pad_token] * padding_len + hist

        return torch.LongTensor(hist), torch.LongTensor(candidates), torch.LongTensor(labels)

    def concat_ints(self, a, b):
        return str(f"{a}{b}")


class BertEvalDatasetNews(BertEvalDataset):

    def __init__(self, u2seq, u2answer, art2words, max_hist_len, mask_token, negative_samples, multiple_eval_items=True):
        super(BertEvalDatasetNews, self).__init__(u2seq, u2answer, max_hist_len, mask_token, negative_samples, multiple_eval_items=multiple_eval_items)

        self.art2words = art2words
        self.max_article_len = len(next(iter(art2words.values())))

    def gen_eval_instance(self, hist, target, negs):
        candidates = target + negs
        candidates = [art_idx2word_ids(cand, self.art2words) for cand in candidates]
        labels = [1] * len(target) + [0] * len(negs)

        hist = [art_idx2word_ids(art, self.art2words) for art in hist[-(self.max_hist_len- 1):]]
        hist = hist + [[self.mask_token] * self.max_article_len]  # predict only the next/last token in seq

        ## apply padding (left-side)
        padding_len = self.max_hist_len - len(hist)

        hist = [[self.pad_token] * self.max_article_len] * padding_len + hist # Padding token := 0
        #
        assert len(hist) == self.max_hist_len

        return torch.LongTensor(hist), torch.LongTensor(candidates), torch.LongTensor(labels)