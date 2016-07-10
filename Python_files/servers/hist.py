import numpy as np
import matplotlib.pyplot as plt
from collections import Counter


fname1 = "testlog20MHzv4.txt"
fname2 = "testlog10MHzv5.txt"
fname3 = "testlog10MHzv4.txt"

data1 = []
data2 = []
data3 = []
with open(fname1,'r') as f:
    for line in f:
        data1.append(int(line))
with open(fname2,'r') as f:
    for line in f:
        data2.append(int(line))
with open(fname3,'r') as f:
    for line in f:
        data3.append(int(line))                
print Counter(data1)
print data1.count(651)/float(len(data1))*100
print Counter(data2)
print data2.count(651)/float(len(data2))*100
print Counter(data3)
print data3.count(651)/float(len(data3))*100