__title__ = 'AREIA: Artificial Redshift Effects for IA'
__author__ = 'Leonardo Ferreira & Clar-Brid Tohill'
__version__ = '0.0.1'

import sys
import argparse
import numpy as np
import glob


from astropy.io import fits
from astropy.cosmology import FlatLambdaCDM  
from astropy.convolution import convolve
from astropy import constants as const
from astropy import units as u

from photutils import detect_sources, detect_threshold

from galclean import central_segmentation_map, measure_background

from scipy.ndimage import zoom

from matplotlib import pyplot as plt


class Config(object):
    '''
        Tracks all the flags used by Artificial Redshift.
        If none is provided, it loads the default defined below.
    '''

    h = 0.7
    cosmo = FlatLambdaCDM(H0=100 * h, Om0=0.3, Tcmb0=2.725)
    add_background = True
    rebinning = True
    convolve_with_psf = True
    make_cutout = True
    dimming = True
    shot_noise = True
    size_correction = True
    evo = False
    evo_alpha = -1

class ObservationFrame(object):
    '''
        Class that represents one observation frame with a given
        instrument setup.
    '''

    def __init__(self, redshift, pixelscale, exptime):
        self.pixelscale = pixelscale
        self.redshift = redshift
        self.exptime = exptime


class ArtificialRedshift(object):
    '''
        This handles all transformations and effects selected
        in the Config class to be applied to the input data,
        from initial_frame to target_frame. It keeps track
        of the transformation in the input image, it is possible 
        to retrieve partial results between each step, ideal for
        debugging.
    '''

    def __init__(self, image, psf, background, initial_frame, target_frame, config=None):

        self.image = image
        self.psf = psf
        self.background = background
        self.initial_frame = initial_frame
        self.target_frame = target_frame

        if config is None:
            self.config = Config()

        self.cosmo = self.config.cosmo

        self.cutout_source() 
        self.geometric_rebinning() 
        self.apply_dimming()
        self.evolution_correction()
        self.convolve_psf()
        self.apply_shot_noise()
        self.add_background()

    @classmethod
    def fromrawdata(cls, image,
                         psf,
                         background,
                         initial_redshift,
                         target_redshift, 
                         initial_pixelscale, 
                         target_pixelscale,
                         obs_exptime, 
                         target_exptime):

        current_frame = ObservationFrame(initial_redshift, initial_pixelscale, obs_exptime)
        target_frame = ObservationFrame(target_redshift, target_pixelscale, target_exptime)
    
        return cls(image, psf, background, initial_frame, target_frame)

    def cutout_source(self):

        if self.config.make_cutout:
            segmentation = central_segmentation_map(self.image)
            self.cutout = self.image.copy()
            self.masked = self.image.copy()
            self.masked[segmentation == True] = 0
            self.cutout[segmentation == False] = 0
            self.final = self.cutout.copy()

    def geometric_rebinning(self):

        def _size_correction(redshift):
            return (1 + redshift)**(-0.97)

        self.size_correction_factor = 1
        if self.config.rebinning:                                                  
            initial_distance = self.cosmo.luminosity_distance(self.initial_frame.redshift).value   
            target_distance = self.cosmo.luminosity_distance(self.target_frame.redshift).value   
            self.scale_factor = (initial_distance * (1 + self.target_frame.redshift)**2 * self.initial_frame.pixelscale) / (target_distance * (1 + self.initial_frame.redshift)**2 * self.target_frame.pixelscale)
            
            if self.config.size_correction:
                self.size_correction_factor = _size_correction(self.target_frame.redshift)

            self.rebinned = zoom(self.image, self.scale_factor * self.size_correction_factor, prefilter=True)
            self.final = self.rebinned.copy()
        else:
            if self.config.size_correction:
                self.size_correction_factor = _size_correction(self.target_frame.redshift)

                self.rebinned = zoom(self.image, self.size_correction_factor, prefilter=True) 
                self.final = self.rebinned.copy()

    def apply_dimming(self):

        if self.config.dimming:
            self.dimming_factor = (self.cosmo.luminosity_distance(self.initial_frame.redshift) / self.cosmo.luminosity_distance(self.target_frame.redshift))**2
            self.dimmed = self.final * self.dimming_factor
            self.final = self.dimmed.copy()


    def evolution_correction(self):
        
        if self.config.evo:
            self.evo_factor = 10**(-0.4 * self.config.evo_alpha * (self.target_frame.redshift))
            self.with_evolution = self.final * self.evo_factor
            self.final = self.with_evolution.copy()


    def convolve_psf(self):
        
        if self.config.convolve_with_psf:
            self.convolved = convolve(self.final, self.psf)   
            self.final = self.convolved.copy()
        
    def apply_shot_noise(self):         
        
        if self.config.shot_noise:
            self.shot_noise = np.sqrt(abs(self.convolved * self.target_frame.exptime)) * np.random.randn(self.convolved.shape[0], self.convolved.shape[1]) / self.target_frame.exptime         
            self.with_shot_noise = self.final + self.shot_noise
            self.final = self.with_shot_noise.copy()


    def add_background(self):

        if self.config.add_background:
            if self.background is None:

                mean, median, std = measure_background(self.image, 2, np.zeros_like(self.image))
                self.background = np.random.normal(mean, std, size=self.image.shape)

            source_shape = self.with_shot_noise.shape
            
            offset = 1
            if source_shape[0] % 2 == 0:
                offset = 0

            offset_min = int(self.background.shape[0]/2) - int(np.floor(source_shape[0]/2)) - offset
            offset_max = int(self.background.shape[0]/2) + int(np.floor(source_shape[0]/2)) 

            self.with_background = self.background.copy()
            self.with_background[offset_min:offset_max, offset_min:offset_max] += self.with_shot_noise
            self.final = self.with_background.copy()






    

    

