# Markov Jump Hamiltonian Monte Carlo
Python implementation of Markov Jump HMC

Markov Jump HMC is described in the paper

> A. Berger, M. Mudigonda, M. R. DeWeese and J. Sohl-Dickstein <br>
> A Markov Jump Process for More Efficient Hamiltonian Monte Carlo <br>
> *arXiv preprint [arXiv:1509.03808](http://arxiv.org/abs/1509.03808)*, 2015

## Example Python Code

```python
from mjhmc.samplers.markov_jump_hmc import MarkovJumpHMC
import numpy as np

# Define the energy function and gradient
def E(X, sigma=1.):
    """ Energy function for isotropic Gaussian """
    return np.sum(X**2, axis=0).reshape((1,-1))/2./sigma**2
    
def dEdX(X, sigma=1.):
    """ Energy function gradient for isotropic Gaussian """
    return X/sigma**2

# Initialize the sample locations -- 2 dimensions, 100 indepedent sampling particles
Xinit = np.random.randn(2,100)

# Initialize the sampler
mjhmc = MarkovJumpHMC(Xinit, E, dEdX, epsilon=0.1, beta=0.1)
# Perform 10 sampling steps for all 100 particles
# Returns an array of samples with shape (ndims, num_steps * num_particles), in this case (2, 1000)
X = mjhmc.sample(num_steps = 10)
```

## Dependencies
### Required
* numpy
* scipy
* pandas

## Optional
* matplotlib
* nosetests
* seaborn (for making pretty plots)
* spearmint (for hyperparameter optimization)

