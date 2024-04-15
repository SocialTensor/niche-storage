from pymongo import MongoClient


client = MongoClient('mongodb://nicheimage:nicheimage2024@3.97.209.185:17001/')

db = client['test']
collection = db['collection_0']

# find all item
for item in collection.find():
    print(1)
    print(item)