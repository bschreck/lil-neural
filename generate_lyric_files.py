from pymongo import MongoClient
import time
import string
import os
import cPickle as pck
import pdb
from collections import Counter, defaultdict
import re
import Levenshtein as lev
import enchant
import inflect
english_d = enchant.Dict("en_US")
inflect_engine = inflect.engine()


def mkdir_recursive(path):
    sub_path = os.path.dirname(path)
    if not os.path.exists(sub_path):
        mkdir_recursive(sub_path)
    if not os.path.exists(path):
        os.mkdir(path)


def generate_files(dirname):
    rappers = db.artists.find({'albums': {'$exists': True}})
    with open('missing_rappers.txt', 'r') as f:
        missing = set([r.replace('\n', '') for r in f.readlines()])
    rappers = [r for r in rappers
               if r['name'] in missing]
    print len(rappers)
    for rap_i, rapper in enumerate(rappers):
        rapper_name = rapper["name"]
        albums = rapper['albums']
        if type(albums) != list:
            iterator = albums.iteritems()
        else:
            iterator = enumerate(albums)

        for album_i, album in iterator:
            album_name = album["name"]
            album_year = album["year"]
            songs = album['songs']
            unknown_song_index = 0

            if type(songs) != list:
                song_iterator = songs.iteritems()
            else:
                song_iterator = enumerate(songs)
            for song_i, song in song_iterator:
                song_name = song["name"]
                if "lyrics" not in song or not song["lyrics"]:
                    continue
                lyrics = song["lyrics"]
                filename = formulate_filename(dirname,
                                              rapper_name,
                                              album_year,
                                              album_name,
                                              song_name)
                if filename.endswith("unknown_song"):
                    filename += str(unknown_song_index)
                    unknown_song_index += 1
                mkdir_recursive(os.path.dirname(filename))
                with open(filename, 'w') as f:
                    if not lyrics[0][0].startswith('(NRP:'):
                        f.write(u'(NRP: {})\n'.format(rapper_name).encode('utf8'))
                    for verse in lyrics:
                        f.write(u'\n'.join(verse).encode('utf8'))
                        f.write(u'\n<eov>\n'.encode('utf8'))


def formulate_filename(dirname, rapper, year, album, song):
    if not year:
        year = "unknown_year"
    if not album:
        album = "unknown_album"
    if not song:
        song = "unknown_song"
    return "/".join([dirname, rapper, str(year), album, song]) + ".txt"

def all_filenames(dirname):
    filenames = []
    for root, dirs, files in os.walk(dirname):
        for file in files:
            if file.endswith(".txt"):
                filenames.append(os.path.join(root, file))
    return filenames

def _word_numbers(num):
    num = num.replace(',','')
    return inflect_engine.number_to_words(num).split()

# TODO: acronyms from extract_features._find_prons
# TODO: manually get pronunciations for most common slang words in corpus
def build_word_dict(filenames):
    begin = time.time()
    trans = [' ']*len(string.punctuation)
    trans[6] = "'"
    trans[11] = ","
    trans[13] = "."
    trans = ''.join(trans)
    replace_punctuation = string.maketrans(string.punctuation, trans)
    commas_decimals = string.maketrans(',.', '  ')
    num = r'(?<!\S)(\d*\.?\d+|\d{1,3}(,\d{3})*(\.\d+)?)(?!\S)'

    dword_to_int = {}
    int_to_dword = {}
    word_to_dwordint = {}
    word_counts = defaultdict(int)
    slang_word_counts = defaultdict(int)
    def add_word(orig, wlist, nondict=[]):
        if orig not in word_to_dwordint:
            wintlist = []
            for w in wlist:
                if w in dword_to_int:
                    wint = dword_to_int[w]
                else:
                    wint = len(dword_to_int)
                    dword_to_int[w] = wint
                    int_to_dword[wint] = w
                wintlist.append(wint)
            word_to_dwordint[orig] = wintlist
        if nondict:
            slang_words = [wlist[i] for i in nondict]
            dwords = [w for i, w in enumerate(wlist)
                      if i not in nondict]
        else:
            slang_words = []
            dwords = wlist
        for w in slang_words:
            slang_word_counts[w] += 1
        for w in dwords:
            word_counts[word] += 1

    for f in filenames:
        with open(f, 'r') as fo:
            words = fo.read()\
                    .replace("<eov>", " ")\
                    .replace("\n", " ")\
                    .replace('\xe2\x80\x99',"'")\
                    .lower()\
                    .translate(replace_punctuation)\
                    .split()
            for word in words:
                numbers = re.findall(num, word)
                if numbers:
                    number = numbers[0][0]
                    nwords = _word_numbers(number)
                    add_word(word, nwords)
                else:
                    cd_split = word.translate(commas_decimals).split()
                    new_words = []
                    nondict = []
                    for i, w in enumerate(cd_split):
                        if english_d.check(w):
                            new_words.append(w)
                        else:
                            suggested = english_d.suggest(w)
                            if len(suggested) and lev.distance(w, suggested[0]) == 1:
                                new_words.append(suggested[0])
                            else:
                                new_words.append(w)
                                nondict.append(i)
                    add_word(word, new_words, nondict=nondict)
    end = time.time()
    print "elapsed:", end - begin
    return word_to_dwordint, dword_to_int, int_to_dword, word_counts, slang_word_counts

def word_count(filenames):
    counter = Counter([])
    replace_punctuation = string.maketrans(string.punctuation, ' '*len(string.punctuation))
    for f in filenames:
        with open(f, 'r') as fo:
            words = fo.read()\
                    .replace("<eov>", " ")\
                    .replace("\n", " ")\
                    .lower()\
                    .translate(replace_punctuation)\
                    .split()
            counter.update(words)
    return counter

def load_word_counts_into_db(collection, word_counts):
    swc = [{"word": w, "count": i} for w,i in word_counts.iteritems()]
    db[collection].insert_many(swc, ordered=False)
def load_word_to_int_dicts_into_db(word_to_dwordint, dword_to_int, int_to_dword):
    db.word_to_dwordint.insert_many([{"word": w, "int_list": wint}
                                     for w, wint in word_to_dwordint.iteritems()],
                                     ordered=False)
    db.dword_to_int.insert_many([{"word": w, "int": wint}
                                  for w, wint in dword_to_int.iteritems()],
                                  ordered=False)

if __name__ == '__main__':
    # manually get prons for top 300 or so
    # have flag for "is_acronym" that will jsut save whether it's an acronym
    # for the feature_extractor
    global client
    global db
    client = MongoClient()
    db = client['lil-neuron-db']
    #generate_files("data/lyric_files")
    # filenames = all_filenames("data/lyric_files")
    # result = build_word_dict(filenames)
    with open('word_stats_new2.p','r') as f:
        res = pck.load(f)
        # pck.dump({
            # 'word_to_dwordint': result[0],
            # 'dword_to_int': result[1],
            # 'int_to_dword': result[2],
            # 'word_counts': result[3],
            # 'slang_word_counts': result[4],
            # }, f)
    load_word_to_int_dicts_into_db(res['word_to_dwordint'],
                                   res['dword_to_int'],
                                   res['int_to_dword'])
    # load_word_counts_into_db("slang_words", res["slang_word_counts"])
    # load_word_counts_into_db("dwords", res["word_counts"])
    #filenames = all_filenames("data/lyric_files/Tyler, The Creator")
