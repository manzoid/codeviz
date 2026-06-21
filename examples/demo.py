class Point:
    def __init__(self, x, y):
        self.x = x
        self.y = y

def shift(p, dx):
    p.x += dx
    return p

a = [1, 2, 3]
b = a            # alias
b.append(4)
counts = {"a": 1, "b": 2}
pt = Point(10, 20)
shift(pt, 5)
print("x =", pt.x)
