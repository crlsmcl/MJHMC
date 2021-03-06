"""
This module contains the TensorflowDistribution base class and distributions that inherit from it
"""

import numpy as np
import tensorflow as tf
from tensorflow.python.client import timeline
from .utils import overrides, package_path
import os
import time
from os.path import expanduser
from scipy import stats
from scipy.io import loadmat
import pickle
from math import sqrt


from mjhmc.misc.distributions import Distribution


class TensorflowDistribution(Distribution):
    """ Base class for distributions defined by energy functions written
    in Tensorflow

    You should give your TensorflowDistribution objects a name. Use a
    descriptive name, and use the same for functionally equivalent
    TensorflowDistributions - the hash of the name is used to label the
    initialization information which is generated at first run time of
    a new distribution. This requirement is a side effect of the
    unfortunate fact that there is no computable hash function which
    assigns functionally identical programs to the same number.

    TensorflowDistribution is subclassed by defining the distribution energy op in
    build_energy_op
    """

    #pylint: disable=too-many-arguments
    def __init__(self, name=None, sess=None, device='/cpu:0', prof_run=False,
                 gpu_frac=1, allow_growth=True, log_placement=False):
        """ Creates a TensorflowDistribution object

        ndims and nbatch are inferred from init
        nbatch must match shape of energy_op

        :param name: name of this distribution. use the same name for functionally identical distributions
        :param sess: optional session. If none, one will be created
        :param device: device to execute tf ops on. By default uses cpu to avoid compatibility issues
        :param prof_run: if True, save a trace so we can profile performance later
        :param gpu_frac: fraction of GPU memory to allocate.
        :param allow_growth: if False, pre-allocate all GPU memory
        :param log_placement: if True, log device placement
        :returns: TensorflowDistribution object
        :rtype: TensorflowDistribution
        """
        self.graph = tf.Graph()


        # if dictionary, use custom device for energy and grad
        if isinstance(device, dict):
            assert 'grad' in device
            assert 'energy' in device
            self.grad_device = device['grad']
            self.energy_device = device['energy']
        elif isinstance(device, str):
            self.grad_device = device
            self.energy_device = device

        self.device = self.energy_device

        self.prof_run = prof_run
        with self.graph.as_default(), tf.device(self.device):
            gpu_options = tf.GPUOptions(per_process_gpu_memory_fraction=gpu_frac, allow_growth=allow_growth)
            sess_config = tf.ConfigProto(allow_soft_placement=True, gpu_options=gpu_options,
                                         log_device_placement=log_placement)
            self.sess = sess or tf.Session(config=sess_config)
            self.build_graph()


        self.name = name or self.energy_op.op.name

        super(TensorflowDistribution, self).__init__(ndims=self.ndims, nbatch=self.nbatch)

        self.backend = 'tensorflow'
        super(TensorflowDistribution, self).__init__(ndims=self.ndims, nbatch=self.nbatch)


    def build_graph(self):
        with self.graph.as_default(), tf.device(self.device):
            self.state_pl = tf.placeholder(tf.float32, [self.ndims, None])
            self.build_energy_op()
            self.grad_op = tf.gradients(self.energy_op, self.state_pl)[0]
            self.sess.run(tf.initialize_all_variables())


    def build_energy_op(self):
        """ Sets self.energy_op

        """
        raise NotImplementedError("this method must be defined to subclass TensorflowDistribution")

    @overrides(Distribution)
    def E_val(self, X):
        with self.graph.as_default(), tf.device(self.energy_device):
            if self.prof_run:
                run_options = tf.RunOptions(trace_level=tf.RunOptions.FULL_TRACE)
                run_metadata = tf.RunMetadata()

                energy = self.sess.run(self.energy_op, feed_dict={self.state_pl: X},
                                       options=run_options, run_metadata=run_metadata)
                tf_tl  = timeline.Timeline(run_metadata.step_stats)
                ctf = tf_tl.generate_chrome_trace_format()
                log_path = expanduser('~/tmp/logs/tf_{}_energy_timeline_{}.json'.format(self.name, time.time()))
                with open(log_path, 'w') as log_file:
                    log_file.write(ctf)
            else:
                energy = self.sess.run(self.energy_op, feed_dict={self.state_pl: X})
            return energy

    @overrides(Distribution)
    def dEdX_val(self, X):
        with self.graph.as_default(), tf.device(self.grad_device):
            if self.prof_run:
                run_options = tf.RunOptions(trace_level=tf.RunOptions.FULL_TRACE)
                run_metadata = tf.RunMetadata()

                grad = self.sess.run(self.grad_op, feed_dict={self.state_pl: X},
                                       options=run_options, run_metadata=run_metadata)

                tf_tl  = timeline.Timeline(run_metadata.step_stats)
                ctf = tf_tl.generate_chrome_trace_format()
                log_path = expanduser('~/tmp/logs/tf_{}_grad_timeline_{}.json'.format(self.name, time.time()))
                with open(log_path, 'w') as log_file:
                    log_file.write(ctf)
            else:
                grad = self.sess.run(self.grad_op, feed_dict={self.state_pl: X})
            return grad

    @overrides(Distribution)
    def __hash__(self):
        return hash((self.ndims, self.name))

class Funnel(TensorflowDistribution):
    """ This class implements the Funnel distribution as specified in Neal, 2003
    In particular:
      x_0 ~ N(0, scale^2)
      x_i ~ N(0, e^x_0); i in {1, ... ,ndims}
    """

    def __init__(self,scale=1.0, nbatch=50, ndims=10, **kwargs):
        self.scale = float(scale)
        self.ndims = ndims
        self.nbatch = nbatch
        self.gen_init_X()

        super(Funnel, self).__init__(name='Funnel', **kwargs)

    @overrides(TensorflowDistribution)
    def build_energy_op(self):
        with self.graph.as_default(), tf.device(self.energy_device):
            # [1, nbatch]
            e_x_0 = tf.neg((self.state_pl[0, :] ** 2) / (self.scale ** 2), name='E_x_0')
            # [ndims - 1, nbatch]
            e_x_k = tf.neg((self.state_pl[1:, :] ** 2) / tf.exp(self.state_pl[0, :]), name='E_x_k')
            # [nbatch]
            self.energy_op = tf.reduce_sum(tf.add(e_x_0, e_x_k), 0, name='energy_op')



    @overrides(Distribution)
    def gen_init_X(self):
        x_0 = np.random.normal(scale=self.scale, size=(1, self.nbatch))
        x_k = np.random.normal(scale=np.exp(x_0), size=(self.ndims - 1, self.nbatch))
        self.Xinit = np.vstack((x_0, x_k))

    @overrides(Distribution)
    def __hash__(self):
        return hash((self.scale, self.ndims))

class TFGaussian(TensorflowDistribution):
    """ Standard gaussian implemented in tensorflow
    """
    def __init__(self, ndims=2, nbatch=100, sigma=1.,  **kwargs):
        self.ndims  = ndims
        self.nbatch = nbatch
        self.sigma = sigma
        self.gen_init_X()

        super(TFGaussian, self).__init__(name='TFGaussian', **kwargs)

    @overrides(TensorflowDistribution)
    def build_energy_op(self):
        with self.graph.as_default(), tf.device(self.energy_device):
            self.energy_op = tf.reduce_sum(self.state_pl ** 2, 0) / (2 * self.sigma ** 2)


    @overrides(Distribution)
    def gen_init_X(self):
        self.Xinit = np.random.randn(self.ndims, self.nbatch)

    @overrides(Distribution)
    def __hash__(self):
        return hash((self.ndims, self.sigma))

class SparseImageCode(TensorflowDistribution):
    """ Distribution over the coefficients in an inference model of sparse coding on natural images a la Olshausen and Field
    """

    def __init__(self, n_patches=9, n_batches=10, cauchy=True, n_basis=1024, **kwargs):
        """ Construct a SparseImageCode object

        Args:
           n_patches: number of patches to simultaneously run inference over
           n_batches: number of batches to run at once
           cauchy: if True uses Cauchy prior, if False, Laplace
        """
        self.max_n_particles = 50
        self.lmbda = 0.01

        assert n_basis in [1024, 512]
        data_path = "{}/distr_data/dump_{}.pkl".format(package_path(), n_basis)
        with open(data_path, 'rb') as dump_file:
            data = pickle.load(dump_file)
            # [256, 1024]
            self.imgs = data['data']
            # [256,  1024], [img_size, n_coeffs]
            self.basis = data['basis']

        # n_coeffs per patch
        self.img_size, self.n_coeffs = self.basis.shape
        self.ndims = n_patches * self.n_coeffs
        self.nbatch = n_batches
        self.n_patches = n_patches
        self.cauchy = cauchy

        # [n_patches, img_size]
        self.patches = self.imgs[:, :n_patches].T

        super(SparseImageCode, self).__init__(name='SparseImageCode', **kwargs)


    @overrides(TensorflowDistribution)
    def build_energy_op(self):
        with self.graph.as_default(), tf.device(self.device):
            n_active = tf.shape(self.state_pl)[1]
            # [n_patches, 1, img_size]
            self.patches = tf.to_float(tf.reshape(self.patches,
                                                  [self.n_patches, 1, self.img_size]),
                                       name='patches')
            shaped_state = tf.reshape(self.state_pl, [self.n_patches, -1, self.n_coeffs, 1], name='shaped_state')

            # [n_patches, nbatch, img_size, n_coeffs]
            full_tiled_basis_arr = np.tile(np.reshape(self.basis, (1, 1, self.img_size, self.n_coeffs)),
                                           (self.n_patches, self.nbatch, 1, 1))
            full_tiled_basis_tf = tf.constant(full_tiled_basis_arr)
            # [n_patches, n_active, img_size, n_coeffs]
            shaped_basis = full_tiled_basis_tf[:, :n_active, :, :]


            # [n_patches, nbatch, img_size]
            reconstructions = tf.batch_matmul(shaped_basis, shaped_state, name='reconstructions')[:, :, :, 0]
            # [n_patches, nbatch]
            reconstruction_error = tf.reduce_sum(0.5 * (self.patches - reconstructions) ** 2, -1)
            # [nbatch]
            reconstruction_error = tf.reduce_mean(reconstruction_error, 0, name='reconstruction_error')

            if self.cauchy:
                sp_penalty = self.lmbda * tf.reduce_sum(tf.log(1 + self.state_pl ** 2), 0, name='sp_penalty')
            else:
                # [nbatch]
                sp_penalty = self.lmbda * tf.reduce_sum(tf.abs(self.state_pl), 0, name='sp_penalty')

            self.energy_op = reconstruction_error + sp_penalty


    @overrides(Distribution)
    def __hash__(self):
        # so they can be hashed
        self.imgs.flags.writeable = False
        self.basis.flags.writeable = False
        return hash((hash(self.imgs.data),
                     hash(self.basis.data),
                     hash(self.lmbda),
                     hash(self.n_patches),
                     self.n_coeffs))
