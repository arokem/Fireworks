import numpy as np
from Fireworks import Message
from Fireworks.toolbox import preprocessing as pr
import numpy as np
from .pipes import ShufflerPipe, BatchingPipe
import math

def test_Normalizer():

    a = 10
    b = 3
    c = 20
    d = 4
    data = Message({'ok': np.random.normal(a,b,1000), 'good': np.random.normal(c,d,1000)})
    shuffler = ShufflerPipe(data)
    batcher = BatchingPipe(shuffler)
    normie = pr.Normalizer(input=batcher)
    normie.disable_inference()
    assert normie.count == 0
    for batch in normie: # Loop through the dataset
        continue
    assert normie.count == 1000
    assert normie.mean == {}
    assert normie.variance == {}
    normie.compile()
    means = normie.mean
    variances = normie.variance
    assert (abs(means['ok'] - a) < .4).all()
    assert (abs(means['good'] - c) < .4).all()
    assert (abs(variances['ok'] - b**2) < 2).all()
    assert (abs(variances['good'] - d**2) < 2).all()
    normie.disable_updates()
    normie.enable_inference()
    for batch in normie:
        mok = np.mean(batch['ok'])
        vok = np.var(batch['ok'])
        mood = np.mean(batch['good'])
        vood = np.var(batch['good'])
        assert abs(mok )< 1
        assert abs(vok - 1 )< 1
        assert abs(mood )< 1
        assert abs(vok -1 )< 1
    normie2 = pr.Normalizer(input=normie)
    normie2.disable_inference()
    for batch in normie2:
        continue
    normie2.compile()
    means = normie2.mean
    variances = normie2.variance
    assert (abs(means['ok']) < .4).all()
    assert (abs(means['good']) < .4).all()
    assert (abs(variances['ok'] - 1) < .4).all()
    assert (abs(variances['good'] - 1) < .4).all()

    assert False
