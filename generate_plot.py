import numpy as np
import matplotlib.pyplot as plt


def generate_plot(array, name):
    r = np.array(array, dtype=[('date', 'S11'), ('rate', float)]).view(np.recarray)

    fig, ax = plt.subplots(1, 1, sharex='none', sharey='none')

    ax.plot(r.date, r.rate, lw=2, )

    ax.grid(True)

    fig.suptitle(name)
    fig.autofmt_xdate()

    plt.savefig(name)
    return name
