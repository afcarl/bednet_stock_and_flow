""" Module to generate empirical priors for the stock-and-flow model
for bednet distribution
"""

from numpy import *
from pymc import *

import simplejson as json
import os

import settings
import data


def llin_discard_rate(recompute=False):
    """ Return the empirical priors for the llin discard rate Beta stoch,
    calculating them if necessary.

    Parameters
    ----------
    recompute : bool, optional
      pass recompute=True to force recomputation of empirical priors, even if json file exists

    Results
    -------
    returns a dict suitable for using to instantiate a Beta stoch
    """
    # load and return, if applicable
    fname = 'emp_prior_reten.json'
    if fname in os.listdir(settings.PATH) and not recompute:
        f = open(settings.PATH + fname)
        return json.load(f)
        
    ### setup (hyper)-prior stochs
    pi = Beta('Pr[net is lost]', 1, 2)
    sigma = InverseGamma('standard error', 11, 1)

    vars = [pi, sigma]

    ### data likelihood from net retention studies
    retention_obs = []
    for d in data.retention:
        @observed
        @stochastic(name='retention_%s_%s' % (d['Name'], d['Year']))
        def obs(value=d['Retention_Rate'],
                T_i=d['Follow_up_Time'],
                pi=pi, sigma=sigma):
            return normal_like(value, (1. - pi) ** T_i, 1. / sigma**2)
        retention_obs.append(obs)

        vars += [retention_obs]
    
    mc = MCMC(vars, verbose=1)
    iter = 10000
    thin = 20
    burn = 20000
    mc.sample(iter*thin+burn, burn, thin)

    x = pi.stats()['mean']
    v = pi.stats()['standard deviation']**2

    print 'mean= %.4f, std= %.4f' % (x, v**.5)

    emp_prior_dict = dict(alpha=x*(x*(1-x)/v-1), beta=(1-x)*(x*(1-x)/v-1))
    f = open(settings.PATH + fname, 'w')
    json.dump(emp_prior_dict, f)

    return emp_prior_dict


def admin_err_and_bias(recompute=False):
    """ Return the empirical priors for the admin error and bias stochs,
    calculating them if necessary.

    Parameters
    ----------
    recompute : bool, optional
      pass recompute=True to force recomputation of empirical priors,
      even if json file exists

    Results
    -------
    returns a dict suitable for using to instantiate a Beta stoch
    """
    # load and return, if applicable
    fname = 'emp_prior_admin.json'
    if fname in os.listdir(settings.PATH) and not recompute:
        f = open(settings.PATH + fname)
        return json.load(f)

    discard_prior = llin_discard_rate()
    mu_pi = discard_prior['alpha'] / (discard_prior['alpha'] + discard_prior['beta'])


    # setup hyper-prior stochs
    sigma = InverseGamma('error in admin dist data', 11., 1.)
    eps = Normal('bias in admin dist data', 0., 1.)
    vars = [sigma, eps]


    ### setup data likelihood stochs
    data_dict = {}
    # store admin data for each country-year
    for d in data.admin_llin:
        key = (d['Country'], d['Year'])
        if not data_dict.has_key(key):
            data_dict[key] = {}
        data_dict[key]['obs'] = d['Program_LLINs']

    # store household data for each country-year
    for d in data.hh_llin_flow:
        key = (d['Country'], d['Year'])
        if not data_dict.has_key(key):
            data_dict[key] = {}
        data_dict[key]['time'] =  d['mean_survey_date'] - (d['Year'] + .5)
        data_dict[key]['truth'] = d['Total_LLINs'] / (1-mu_pi)**data_dict[key]['time']
        data_dict[key]['se'] = d['Total_st']
        
    # keep only country-years with both admin and survey data
    for key in data_dict.keys():
        if len(data_dict[key]) != 4:
            data_dict.pop(key)

    # create the observed stochs
    for d in data_dict.values():
        @observed
        @stochastic
        def obs(value=log(d['obs']), log_truth=log(d['truth']),
                log_v=1.1*d['se']**2/d['truth']**2,
                eps=eps, sigma=sigma):
            return normal_like(value, log_truth + eps,
                               1. / (log_v + sigma**2))
        vars.append(obs)


    # sample from empirical prior distribution via MCMC
    mc = MCMC(vars, verbose=1)
    iter = 10000
    thin = 20
    burn = 20000

    mc.sample(iter*thin+burn, burn, thin)


    # output information on empirical prior distribution
    emp_prior_dict = dict(
        sigma=dict(mu=sigma.stats()['mean'], tau=sigma.stats()['standard deviation']**-2),
        eps=dict(mu=eps.stats()['mean'], tau=eps.stats()['standard deviation']**-2))
    print emp_prior_dict

    f = open(settings.PATH + fname, 'w')
    json.dump(emp_prior_dict, f)

    return emp_prior_dict


def cov_and_zif_fac(recompute=False):
    """ Return the empirical priors for the coverage factor and
    zero-inflation factor, calculating them if necessary.

    Parameters
    ----------
    recompute : bool, optional
      pass recompute=True to force recomputation of empirical priors,
      even if json file exists

    Results
    -------
    returns a dict suitable for using to instantiate normal and beta stochs
    """
    # load and return, if applicable
    fname = 'emp_prior_cov.json'
    if fname in os.listdir(settings.PATH) and not recompute:
        f = open(settings.PATH + fname)
        return json.load(f)

    # setup hyper-prior stochs
    e = Normal('coverage factor', 5., 3.)
    z = Beta('zero inflation factor', 1., 10.)
    vars = [e, z]


    ### setup data likelihood stochs
    data_dict = {}

    # store population data for each country-year
    for d in data.population:
        key = (d['Country'], d['Year'])
        data_dict[key] = {}
        data_dict[key]['pop'] =  d['Pop']*1000

    # store stock data for each country-year
    for d in data.hh_llin_stock:
        key = (d['Country'], d['Survey_Year2'])
        data_dict[key]['stock'] = d['SvyIndex_LLINstotal'] / data_dict[key]['pop']
        data_dict[key]['stock_se'] = d['SvyIndex_st'] / data_dict[key]['pop']

    # store coverage data for each country-year
    for d in data.llin_coverage:
        key = (d['Country'], d['Survey_Year2'])
        data_dict[key]['uncovered'] =  d['Per_0LLINs']
        data_dict[key]['se'] = d['LLINs0_SE']
        
    # keep only country-years with both stock and coverage
    for key in data_dict.keys():
        if len(data_dict[key]) != 5:
            data_dict.pop(key)

    # create stochs from stock and coverage data
    for k, d in data_dict.items():
        stock = Normal('stock_%s_%s' % k, mu=d['stock'], tau=d['stock_se']**-2)
        
        @observed
        @stochastic
        def obs(value=d['uncovered'], stock=stock, tau=d['se']**-2,
                e=e, z=z):
            return normal_like(value, z + (1-z) * exp(-e * stock), tau)
        vars += [stock, obs]


    # sample from empirical prior distribution via MCMC
    mc = MCMC(vars, verbose=1)
    iter = 10000
    thin = 20
    burn = 20000

    mc.sample(iter*thin+burn, burn, thin)


    # output information on empirical prior distribution
    emp_prior_dict = dict(
        eta=dict(mu=e.stats()['mean'], tau=e.stats()['standard deviation']**-2),
        zeta=dict(mu=z.stats()['mean'], tau=z.stats()['standard deviation']**-2))
    print emp_prior_dict

    f = open(settings.PATH + fname, 'w')
    json.dump(emp_prior_dict, f)

    return emp_prior_dict


if __name__ == '__main__':
    usage = 'usage: %prog [options]'
    parser = optparse.OptionParser(usage)
    (options, args) = parser.parse_args()

    if len(args) != 0:
        parser.error('incorrect number of arguments')

    llin_discard_rate(recompute=True)
    admin_err_and_bias(recompute=True)
    cov_and_zif_fac(recompute=True)