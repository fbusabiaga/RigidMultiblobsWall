'''This script will display a histogram of a single non-spherical particle's height when next to a wall using non_sphere.py.
1,000,000 heights will be generated by iterating over n_steps, and written to a text file: rejection_locations.txt
On top of the histogram is a plot of the analytical GB distribution  
Prints the time taken for all the calculations'''

import numpy as np
import time
import non_sphere as s
import sys
sys.path.append('..')
from quaternion_integrator.quaternion import Quaternion

outFile = 'ns_rejection_locations.txt'
# constants listed for convenience, none here are changed from what is in non_sphere.py
num_blobs = 7
s.A = 0.265*np.sqrt(3./2.) # radius of blob in um
s.VISCOSITY = 8.9e-4
s.BLOB_WEIGHT = 1.*0.0000000002*(9.8*1e6)
s.WEIGHT = [s.BLOB_WEIGHT/num_blobs for i in range(num_blobs)] # weight of entire boomerang particle
s.KT = 300.*1.3806488e-5
s.REPULSION_STRENGTH = 7.5 * s.KT
s.DEBYE_LENGTH = 0.5*s.A


# initial configuration
theta = (1, 0, 0, 0)
orientation = Quaternion(theta/np.linalg.norm(theta)) # orientation is a quaternion object
location = [0., 0., 1.1] # the position of the particle
#sample = [location, orientation]

n_steps = 1000000 # the number of height positions to be generated
f = open(outFile, 'w')

start_time = time.time() 

# generate appropriate normalization constant
partition_steps = 10000
partitionZ = s.generate_non_sphere_partition(partition_steps)

for i in range(n_steps):
	# get a position from rejection function
	sample_state = s.non_sphere_rejection(partitionZ)
	# send that position to the data file
	f.write(str(sample_state[0][2]) + '\n')
f.close()

end_time = time.time() - start_time
print end_time # should take somewhere around 80 seconds for one million heights

num_points = 100000
x, y = s.analytical_distribution_non_sphere(num_points) # calculate points for the analytical curve
s.plot_distribution(outFile, x, y, n_steps) # generate historgram and analytical curve