#1. Bisect module - uses binary search(searching and inserting function)
#bisect(haystack, needle) - returns the index where the needle should be inserted to maintain sorted order
#haystack.insert(index, needle) - find index using bisect then insert the needle at that index'
#insort does both, finds and inserts the needle at the correct index to maintain sorted order
import bisect 
import sys

HAYSTACK = [1, 4, 5, 6, 8, 12, 15, 20, 21, 23, 23, 26, 29, 30]
NEEDLES = [0, 1, 2, 5, 8, 10, 22, 23, 29, 30, 31]

ROW_FMT = '{0:2d} @ {1:2d} {2}{0:<2d}'

def demo(bisect_fn):
    for needle in reversed(NEEDLES):
        position = bisect_fn(HAYSTACK, needle)
        offset = position * '  |'
        print(ROW_FMT.format(needle, position, offset))


# driver part of python script
if __name__ == '__main__': #this part only runs when file is run directly and not imported as a module
    if sys.argv[-1] == 'left':
        bisect_fn = bisect.bisect_left
    else:
        bisect_fn = bisect.bisect_right # if run python script.py left, it uses bisect_left else right
        ##bisect_left - if element already exisist the value is inserted to the left of exisitng value, vice verse for bisect_right

    print('DEMO:', bisect_fn.__name__)  # (5)
    print('haystack ->', ' '.join(f'{n:2}' for n in HAYSTACK))
    demo(bisect_fn)

breakpoints = [60,70,80,90]
grades='FDCBA'
def grade(score):
    i = bisect.bisect(breakpoints, score)
    return grades[i]

print([grade(score) for score in [33, 99, 77, 70, 89, 90, 100]])

#insort
import random

SIZE = 7

random.seed(1729)

my_list = []
for i in range(SIZE):
    new_item = random.randrange(SIZE * 2)
    bisect.insort(my_list, new_item)
    print(f'{new_item:2d} -> {my_list}')


#@property deifined a method in a class that can be called liek an attribute without parentheses. It is used to define a getter method for a property of a class. When you access the property, the getter method is automatically called, and its return value is returned as the value of the property. This allows you to encapsulate the logic for calculating or retrieving the value of a property while still providing a simple and intuitive interface for accessing it.
#@__repr__ is present with every data types deinfition, when print is called ti refers to that datatypes __repr__
# we can use__repr__ to provide a string representation of an object that is useful for debugging and development. It can be used to display the internal state of an object, including its attributes and their values, in a human-readable format. This can help developers understand how an object is structured and how it behaves in different contexts. Additionally, __repr__ can be used to create a string representation of an object that can be used to recreate the object later, which can be useful for serialization and deserialization.