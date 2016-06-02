from pyparsing import *

string = "#def\n"+"var A0\n"+"#enddef\n"+"\n"+"#def\n"+"var T_start = 10\n"+"#enddef\n"
string +="\n"+"#repeat i=0,i+1,i<1\n"+"\n"+"Channel DDS_2 do 0.1  MHz with  10 dBm for 2 ms at (100+4*i) ms in mode Normal\n"
string +="\n"+"#endrepeat\n\n\n"+"Channel DDS_2 do 0.1e-3  MHz with 10 dBm for T_start ms at 40 ms in mode Normal\n"
string +="\n"+"#repeat i=0,i+10,i<1\n"+"\n"+"Channel DDS_3 do 0.1  MHz with  10 dBm for 2 ms at (100+4*i) ms in mode Normal\n#endrepeat"
#print string
point = Literal( '.' )
colon = Literal( ',' )
minus = Literal( '-' )

number = Word( nums )
integer = Combine( Optional( minus ) + number )
floatnumber = Combine(integer + Optional( point + Optional( number ) ) +Optional( 'E'|'e' + (Optional(minus)) + integer ))
parameter = ( Word(alphas)("Keyword") + 
             ((floatnumber("value") | Word(printables)("varvalue"))  
                   +Word(alphas)("Units") ) |
              "mode" + Word (alphas)("Mode"))

loopparameter = ( Word(alphas)("Keyword") + Optional('(') +
             ((floatnumber("value") | Word(printables)("varvalue")) + Optional(')')  
                   +Word(alphas)("Units") ) |
              "mode" + Word (alphas)("Mode"))
name = 'Channel' + Word(printables)("name")


defs = '#def' + SkipTo("#enddef",include=True)


Pulse = name + OneOrMore(parameter) + LineEnd()

looppulses = name + OneOrMore(loopparameter) + LineEnd()
loops = '#repeat' + SkipTo("#endrepeat",include=True)


def recurseloops(loops,string):
    for match,start,end in loops.scanString(string):
        print match
        if None in [start,end]:
            return match
        else:
            string = string[:]
            return recurseloops(loops,string)
        
recurseloops(loops,string)
#for match,start,end in defs.scanString(string):

full = ZeroOrMore(defs) & ZeroOrMore(loops) & ZeroOrMore(Pulse)
try:
    res = full.scanString(string)

except ParseException,e:
    print e