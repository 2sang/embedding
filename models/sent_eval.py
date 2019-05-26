import sys, requests, random
sys.path.append('models')

import tensorflow as tf
from bert.modeling import BertModel, BertConfig
from bert.tokenization import FullTokenizer, convert_to_unicode
from bilm import Batcher, BidirectionalLanguageModel, weight_layers
from preprocess import get_tokenizer, post_processing
from collections import defaultdict

import numpy as np
from lxml import html
from gensim.models import Doc2Vec, LdaModel
from visualize_utils import visualize_homonym, visualize_between_sentences, \
    visualize_self_attention_scores, visualize_sentences, visualize_words, visualize_between_words
from tune_utils import make_elmo_graph, make_bert_graph
from sklearn.preprocessing import normalize


class Doc2VecEvaluator:

    def __init__(self, model_fname="data/doc2vec.vecs"):
        self.model = Doc2Vec.load(model_fname)
        self.doc2idx = {el:idx for idx, el in enumerate(self.model.docvecs.doctags.keys())}

    def most_similar(self, movie_id, topn=10):
        similar_movies = self.model.docvecs.most_similar('MOVIE_' + str(movie_id), topn=topn)
        for movie_id, score in similar_movies:
            print(self.get_movie_title(movie_id), score)

    def get_titles_in_corpus(self, n_sample=5):
        movie_ids = random.sample(self.model.docvecs.doctags.keys(), n_sample)
        return {movie_id: self.get_movie_title(movie_id) for movie_id in movie_ids}

    def get_movie_title(self, movie_id):
        url = 'http://movie.naver.com/movie/point/af/list.nhn?st=mcode&target=after&sword=%s' % movie_id.split("_")[1]
        resp = requests.get(url)
        root = html.fromstring(resp.text)
        try:
            title = root.xpath('//div[@class="choice_movie_info"]//h5//a/text()')[0]
        except:
            title = ""
        return title

    def visualize_movies(self, n_sample=100, palette="Viridis256", type="between"):
        movie_ids = self.get_titles_in_corpus(n_sample=n_sample)
        movie_titles = [movie_ids[key] for key in movie_ids.keys()]
        movie_vecs = [self.model.docvecs[self.doc2idx[movie_id]] for movie_id in movie_ids.keys()]
        if type == "between":
            visualize_between_words(movie_titles, movie_vecs, palette)
        else:
            visualize_words(movie_titles, movie_vecs, palette)


class LDAEvaluator:

    def __init__(self, results_fname="data/lda.results",
                 model_fname="data/lda.model", tokenizer_name="mecab",
                 vis_fname="data/lda.vis"):
        self.all_topics = self.load_results(results_fname)
        self.tokenizer = get_tokenizer(tokenizer_name)
        self.model = LdaModel.load(model_fname)
        self.vis_fname = vis_fname

    def load_results(self, results_fname):
        topic_dict = defaultdict(list)
        with open(results_fname, 'r', encoding='utf-8') as f:
            for line in f:
                sentence, _, topic_id, prob = line.strip().split("\u241E")
                topic_dict[int(topic_id)].append((sentence, float(prob)))
        for key in topic_dict.keys():
            topic_dict[key] = sorted(topic_dict[key], key=lambda x: x[1], reverse=True)
        return topic_dict

    def show_topic_docs(self, topic_id, topn=10):
        return self.all_topics[topic_id][:topn]

    def show_topic_words(self, topic_id, topn=10):
        return self.model.show_topic(topic_id, topn=topn)

    def show_new_document_topic(self, documents):
        tokenized_documents = [self.tokenizer.morphs(document) for document in documents]
        curr_corpus = [self.model.id2word.doc2bow(tokenized_document) for tokenized_document in tokenized_documents]
        topics = self.model.get_document_topics(curr_corpus, minimum_probability=0.5, per_word_topics=False)
        for doc_idx, topic in enumerate(topics):
            if len(topic) == 1:
                topic_id, prob = topic[0]
                print(documents[doc_idx], ", topic id:", str(topic_id), ", prob:", str(prob))
            else:
                print(documents[doc_idx], ", there is no dominant topic")


class LSAEvaluator:

    def __init__(self, model_fname="data/lsa-tfidf.vecs"):
        self.titles, self.vectors = self.load_model(model_fname)

    def most_similar(self, doc_id, topn=10):
        query_doc_vec = self.vectors[doc_id]
        query_vec_norm = np.linalg.norm(query_doc_vec)
        if query_vec_norm != 0:
            query_unit_vec = query_doc_vec / query_vec_norm
        else:
            query_unit_vec = query_doc_vec
        query_sentence = self.titles[doc_id]
        scores = np.dot(self.vectors, query_unit_vec)
        return [query_sentence, sorted(zip(self.titles, scores), key=lambda x: x[1], reverse=True)[1:topn + 1]]

    def load_model(self, model_fname):
        titles, vectors = [], []
        with open(model_fname, 'r', encoding='utf-8') as f:
            for line in f:
                title, _, str_vec = line.strip().split("\u241E")
                vector = [float(el) for el in str_vec.split()]
                titles.append(title)
                vectors.append(vector)
        return titles, normalize(vectors, axis=1, norm='l2')

    def visualize(self, mode="between", num_sents=30, palette="Viridis256"):
        doc_idxes = random.sample(range(len(self.titles)), num_sents)
        sentences = [self.titles[idx] for idx in doc_idxes]
        vecs = [self.vectors[idx] for idx in doc_idxes]
        if mode == "between":
            visualize_between_sentences(sentences, vecs, palette)
        else:
            visualize_sentences(vecs, sentences, palette)


class SentenceEmbeddingEvaluator:

    def __init__(self, model_name, dimension):
        # reset graphs.
        tf.reset_default_graph()
        self.model_name = model_name
        self.dimension = dimension

    def get_token_vector_sequence(self, sentence):
        raise NotImplementedError

    def get_sentence_vector(self, sentence):
        raise NotImplementedError

    def predict(self, sentence):
        raise NotImplementedError

    def tokenize(self, sentence):
        raise NotImplementedError

    def make_input(self, tokens):
        raise NotImplementedError

    def visualize_homonym(self, homonym, sentences, palette="Viridis256"):
        tokenized_sentences = []
        vecs = np.zeros((1, self.dimension))
        for sentence in sentences:
            tokens, vec = self.get_token_vector_sequence(sentence)
            tokenized_sentences.append(tokens)
            vecs = np.concatenate([vecs, vec], axis=0)
        visualize_homonym(homonym, tokenized_sentences, vecs, self.model_name, palette)

    def visualize_sentences(self, sentences, palette="Viridis256"):
        vecs = np.array([model.get_sentence_vector(sentence)[1] for sentence in sentences])
        visualize_sentences(vecs, sentences, palette)

    def visualize_between_sentences(self, sentences, palette="Viridis256"):
        vec_list = []
        for sentence in sentences:
            _, vec = self.get_sentence_vector(sentence)
            vec_list.append(vec)
        visualize_between_sentences(sentences, vec_list, palette)


class BERTEmbeddingEvaluator(SentenceEmbeddingEvaluator):

    def __init__(self, model_fname="data/bert",
                 bertconfig_fname="data/bert/multi_cased_L-12_H-768_A-12/bert_config.json",
                 vocab_fname="data/bert/multi_cased_L-12_H-768_A-12/vocab.txt",
                 max_seq_length=32, dimension=768, num_labels=2):

        super().__init__("bert", dimension)
        config = BertConfig.from_json_file(bertconfig_fname)
        self.max_seq_length = max_seq_length
        self.tokenizer = FullTokenizer(vocab_file=vocab_fname, do_lower_case=False)
        self.model, self.input_ids, self.input_mask, self.segment_ids, self.probs = make_bert_graph(config,
                                                                                                    max_seq_length,
                                                                                                    1.0,
                                                                                                    num_labels,
                                                                                                    tune=False)
        saver = tf.train.Saver(tf.global_variables())
        self.sess = tf.Session()
        checkpoint_path = tf.train.latest_checkpoint(model_fname)
        saver.restore(self.sess, checkpoint_path)

    def predict(self, sentence):
        tokens = self.tokenize(sentence)
        model_input = self.make_input(tokens)
        probs = self.sess.run(self.probs, model_input)
        return probs

    """
    sentence를 입력하면 토크나이즈 결과와 token 벡터 시퀀스를 반환한다
        - shape :[[# of tokens], [batch size, max seq length, dimension]]
    """
    def get_token_vector_sequence(self, sentence):
        tokens = self.tokenize(sentence)
        model_input = self.make_input(tokens)
        return [tokens, self.sess.run(self.model.get_sequence_output()[0], model_input)[:len(tokens)]]

    """
    sentence를 입력하면 토크나이즈 결과와 [CLS] 벡터를 반환한다
         - shape :[[# of tokens], [batch size, dimension]]
    """
    def get_sentence_vector(self, sentence):
        tokens = self.tokenize(sentence)
        model_input = self.make_input(tokens)
        return [tokens, self.sess.run(self.model.pooled_output, model_input)[0]]

    """
    sentence를 입력하면 토크나이즈 결과와 self-attention score matrix를 반환한다
        - shape :[[# of tokens], [batch size, # of tokens, # of tokens]]
    """
    def get_self_attention_score(self, sentence):
        tokens = self.tokenize(sentence)
        model_input = self.make_input(tokens)
        # raw_score : shape=[# of layers, batch_size, num_attention_heads, max_seq_length, max_seq_length]
        raw_score = self.sess.run(self.model.attn_probs_for_visualization_list, model_input)
        # 마지막 레이어를 취한 뒤, attention head 기준(axis=0)으로 sum
        scores = np.sum(raw_score[-1][0], axis=0)
        # scores matrix에서 토큰 개수만큼 취함
        scores = scores[:len(tokens), :len(tokens)]
        return [tokens, scores]

    def tokenize(self, sentence):
        return self.tokenizer.tokenize(convert_to_unicode(sentence))

    def make_input(self, tokens):
        tokens = tokens[:(self.max_seq_length - 2)]
        token_sequence = ["[CLS]"] + tokens + ["[SEP]"]
        segment = [0] * len(token_sequence)
        sequence = self.tokenizer.convert_tokens_to_ids(token_sequence)
        current_length = len(sequence)
        padding_length = self.max_seq_length - current_length
        input_feed = {
            self.input_ids: np.array([sequence + [0] * padding_length]),
            self.segment_ids: np.array([segment + [0] * padding_length]),
            self.input_mask: np.array([[1] * current_length + [0] * padding_length])
        }
        return input_feed

    def visualize_self_attention_scores(self, sentence, palette="Viridis256"):
        tokens, scores = self.get_self_attention_score(sentence)
        visualize_self_attention_scores(tokens, scores, palette)


class ELMoEmbeddingEvaluator(SentenceEmbeddingEvaluator):

    def __init__(self, tune_model_fname="data/elmo",
                 pretrain_model_fname="data/elmo/elmo.model",
                 options_fname="data/elmo/options.json",
                 vocab_fname="data/elmo/elmo-vocab.txt",
                 max_characters_per_token=30, dimension=256, num_labels=2):

        # configurations
        super().__init__("elmo", dimension)
        self.tokenizer = get_tokenizer("mecab")
        self.batcher = Batcher(lm_vocab_file=vocab_fname, max_token_length=max_characters_per_token)
        self.ids_placeholder, self.elmo_embeddings, self.probs = make_elmo_graph(options_fname,
                                                                                 pretrain_model_fname,
                                                                                 max_characters_per_token,
                                                                                 num_labels, tune=False)
        # restore model
        saver = tf.train.Saver(tf.global_variables())
        self.sess = tf.Session()
        checkpoint_path = tf.train.latest_checkpoint(tune_model_fname)
        saver.restore(self.sess, checkpoint_path)

    def predict(self, sentence):
        tokens = self.tokenize(sentence)
        model_input = self.make_input(tokens)
        probs = self.sess.run(self.probs, model_input)
        return probs

    """
    sentence를 입력하면 토크나이즈 결과와 token 벡터 시퀀스를 반환한다
        - shape :[[# of tokens], [batch size, max seq length, dimension]]
    """
    def get_token_vector_sequence(self, sentence):
        tokens = self.tokenize(sentence)
        model_input = self.make_input(tokens)
        sentence_vector = self.sess.run(self.elmo_embeddings['weighted_op'], model_input)
        return [tokens, sentence_vector[0]]

    """
    sentence를 입력하면 토크나이즈 결과와 토큰 시퀀스의 마지막 벡터를 반환한다
    ELMo는 Language Model이기 때문에 토큰 시퀀스 마지막 벡터에 많은 정보가 녹아 있다
         - shape :[[# of tokens], [batch size, dimension]]
    """
    def get_sentence_vector(self, sentence):
        tokens, vecs = self.get_token_vector_sequence(sentence)
        return [tokens, vecs[-1]]

    def tokenize(self, sentence):
        tokens = self.tokenizer.morphs(sentence)
        return post_processing(tokens)

    def make_input(self, tokens):
        model_input = self.batcher.batch_sentences([tokens])
        input_feed = {self.ids_placeholder: model_input}
        return input_feed


import csv, random
sentences = []
with open("data/kor_pair_train.csv", "r", encoding="utf-8") as f:
    reader = csv.reader(f, delimiter=",")
    next(reader) # skip head line
    for line in reader:
        _, _, _, sent1, sent2, _ = line
        sentences.append(sent1)
        sentences.append(sent2)
sampled_sentences = random.sample(sentences, 30)

positive_reviews, negative_reviews = [], []
with open("data/ratings_train.txt", "r", encoding="utf-8") as f:
    reader = csv.reader(f, delimiter="\t")
    next(reader) # skip head line
    for line in reader:
        _, sentence, label = line
        if label == '1':
            positive_reviews.append(sentence)
        else:
            negative_reviews.append(sentence)
sampled_reviews = random.sample(positive_reviews, 5)
sampled_reviews.extend(random.sample(negative_reviews, 5))


# BERT
model = BERTEmbeddingEvaluator()
model.get_sentence_vector("나는 학교에 간다")
model.get_token_vector_sequence("나는 학교에 간다")
model.visualize_homonym("배", ["배 고프다", "배 아프다", "배 나온다", "배가 불렀다",
                                "배는 사과보다 맛있다", "배는 수분이 많은 과일이다", "배를 깎아 먹다",
                                "배를 바다에 띄웠다", "배 멀미가 난다"])
model.visualize_self_attention_scores("배가 아파서 병원에 갔어")
model.predict("이 영화 정말 재미 있다")
model.visualize_between_sentences(sampled_sentences)
model.visualize_sentences(sampled_sentences)


# ELMo
model = ELMoEmbeddingEvaluator()
model.get_sentence_vector("나는 학교에 간다")
model.get_token_vector_sequence("나는 학교에 간다")
model.visualize_homonym("배", ["배가 고파서 밥 먹었어", "배가 아파서 병원에 갔어",  "고기를 많이 먹으면 배가 나온다",
                                "사과와 배는 맛있어", "갈아만든 배", "감기에 걸렸을 땐 배를 달여 드세요",
                                "항구에 배가 많다", "배를 타면 멀미가 난다", "배를 건조하는 데 돈이 많이 든다"])
model.predict("이 영화 정말 재미 있다")
model.visualize_between_sentences(sampled_sentences)
model.visualize_sentences(sampled_reviews)


# Doc2Vec
model = Doc2VecEvaluator()
model.get_titles_in_corpus(n_sample=30)
model.visualize_movies()
model.visualize_movies(type="between")
model.most_similar("36843") # 러브 액츄얼리
model.most_similar("19227") # 스파이더맨
model.most_similar("24479") # 스타워즈: 에피소드 1
model.most_similar("83893") # 광해 왕이된 남자


# LDA
model = LDAEvaluator()
model.show_topic_docs(topic_id=1)
model.show_topic_words(topic_id=0)
model.show_new_document_topic(["너무 사랑스러운 영화", "인생을 말하는 영화"])


# LSA
model = LSAEvaluator()
model.most_similar(doc_id=111)
model.visualize(mode="between", num_sents=10)