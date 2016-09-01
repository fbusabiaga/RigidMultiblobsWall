import numpy as np
import time
import sys
import subprocess
import cPickle
import many_body_potential_pycuda as pycuda
sys.path.append('..')
from body import body
from quaternion_integrator.quaternion import Quaternion
from read_input import read_input
from read_input import read_vertex_file, read_clones_file
import utils


def get_blobs_r_vectors(bodies, Nblobs):
  '''
  Return coordinates of all the blobs with shape (Nblobs, 3).
  '''
  r_vectors = np.empty((Nblobs, 3))
  offset = 0
  for b in bodies:
    num_blobs = b.Nblobs
    r_vectors[offset:(offset+num_blobs)] = b.get_r_vectors()
    offset += num_blobs
  return r_vectors


if __name__ == '__main__':

  # script takes input file as command line argument or default 'data.main'
  if len(sys.argv) != 2: 
    input_file = 'data.main'
  else:
    input_file = sys.argv[1]

  # Read input file
  read = read_input.ReadInput(input_file) 

  # Copy input file to output
  subprocess.call(["cp", input_file, read.output_name + '.inputfile'])

  # Set random generator state
  if read.random_state is not None:
    with open(read.random_state, 'rb') as f:
      np.random.set_state(cPickle.load(f))
  elif read.seed is not None:
    np.random.seed(int(read.seed))
  
  # Save random generator state
  with open(read.output_name + '.random_state', 'wb') as f:
    cPickle.dump(np.random.get_state(), f)

  # Parameters from the input file
  blob_radius = read.blob_radius
  periodic_length = read.periodic_length
  max_translation = blob_radius
  weight = 1.0 * read.g
  kT = read.kT

  # Some other parameters
  max_starting_height = kT/(weight*7)*12 + blob_radius + 4.0 * read.debye_length_wall
  epsilon = 0.095713728509
  boom1_cross, boom2_cross = 6, 21 # for two size 15 boomerangs
  
  # Create rigid bodies
  bodies = []
  body_types = []
  max_body_length = 0.0
  for ID, structure in enumerate(read.structures):
    print 'Creating structures = ', structure[1]
    struct_ref_config = read_vertex_file.read_vertex_file(structure[0])
    num_bodies_struct, struct_locations, struct_orientations = read_clones_file.read_clones_file(structure[1])
    body_types.append(num_bodies_struct)
    # Creat each body of type structure
    for i in range(num_bodies_struct):
      b = body.Body(struct_locations[i], struct_orientations[i], struct_ref_config, blob_radius)
      b.ID = read.structures_ID[ID]
      body_length = b.calc_body_length()
      max_body_length = (body_length if body_length > max_body_length else max_body_length)
      bodies.append(b)
  bodies = np.array(bodies)

  # Set some more variables
  num_of_body_types = len(read.structure_names)
  num_bodies = bodies.size
  Nblobs = sum([x.Nblobs for x in bodies])
  max_angle_shift = max_translation / max_body_length
  accepted_moves = 0

  # Create blobs coordinates array
  sample_r_vectors = get_blobs_r_vectors(bodies, Nblobs)

  # begin MCMC
  # get energy of the current state before jumping into the loop
  start_time = time.time()
  current_state_energy = pycuda.compute_total_energy(bodies,
                                                     sample_r_vectors,
                                                     periodic_length = periodic_length,
                                                     debye_length_wall = read.debye_length_wall,
                                                     repulsion_strength_wall = read.repulsion_strength_wall,
                                                     debye_length = read.debye_length,
                                                     repulsion_strength = read.repulsion_strength,
                                                     weight = weight,
                                                     blob_radius = blob_radius)

  # quaternion to be used for disturbing the orientation of each body
  quaternion_shift = Quaternion(np.array([1,0,0,0]))

  # for each step in the Markov chain, disturb each body's location and orientation and obtain the new list of r_vectors
  # of each blob. Calculate the potential of the new state, and accept or reject it according to the Markov chain rules:
  # 1. if Ej < Ei, always accept the state  2. if Ej < Ei, accept the state according to the probability determined by
  # exp(-(Ej-Ei)/kT). Then record data.
  # Important: record data also when staying in the same state (i.e. when a sample state is rejected)
  for step in range(read.initial_step, read.n_steps):
    blob_index = 0
    for i, body in enumerate(bodies): # distrub bodies
      body.location_new = body.location + np.random.uniform(-max_translation, max_translation, 3) # make small change to location
      quaternion_shift = Quaternion.from_rotation(np.random.normal(0,1,3) * max_angle_shift)
      body.orientation_new = quaternion_shift * body.orientation
      sample_r_vectors[blob_index : blob_index + bodies[i].Nblobs] = body.get_r_vectors(body.location_new, body.orientation_new)
      blob_index += body.Nblobs

    # calculate potential of proposed new state
    sample_state_energy = pycuda.compute_total_energy(bodies,
                                                      sample_r_vectors,
                                                      periodic_length = periodic_length,
                                                      debye_length_wall = read.debye_length_wall,
                                                      repulsion_strength_wall = read.repulsion_strength_wall,
                                                      debye_length = read.debye_length,
                                                      repulsion_strength = read.repulsion_strength,
                                                      weight = weight,
                                                      blob_radius = blob_radius)

    # accept or reject the sample state and collect data accordingly
    if np.random.uniform(0.0, 1.0) < np.exp(-(sample_state_energy - current_state_energy) / kT):
      current_state_energy = sample_state_energy
      accepted_moves += 1
      for body in bodies:
        body.location, body.orientation = body.location_new, body.orientation_new
	
    # Save data if...
    if (step % read.n_save) == 0 and step >= 0:
      elapsed_time = time.time() - start_time
      print 'MCMC, step = ', step, ', wallclock time = ', time.time() - start_time, ', acceptance ratio = ', accepted_moves / (step+1.0-read.initial_step)
      # For each type of structure save locations and orientations to one file
      body_offset = 0
      if read.save_clones == 'one_file_per_step':
        for i, ID in enumerate(read.structures_ID):
          name = read.output_name + '.' + ID + '.' + str(step).zfill(8) + '.clones'
          with open(name, 'w') as f_ID:
            f_ID.write(str(body_types[i]) + '\n')
            for j in range(body_types[i]):
              orientation = bodies[body_offset + j].orientation.entries
              f_ID.write('%s %s %s %s %s %s %s\n' % (bodies[body_offset + j].location[0], 
                                                     bodies[body_offset + j].location[1], 
                                                     bodies[body_offset + j].location[2], 
                                                     orientation[0], 
                                                     orientation[1], 
                                                     orientation[2], 
                                                     orientation[3]))
            body_offset += body_types[i]
      elif read.save_clones == 'one_file':
        for i, ID in enumerate(read.structures_ID):
          name = read.output_name + '.' + ID + '.config'
          if step == 0:
            status = 'w'
          else:
            status = 'a'
          with open(name, status) as f_ID:
            f_ID.write(str(body_types[i]) + '\n')
            for j in range(body_types[i]):
              orientation = bodies[body_offset + j].orientation.entries
              f_ID.write('%s %s %s %s %s %s %s\n' % (bodies[body_offset + j].location[0], 
                                                     bodies[body_offset + j].location[1], 
                                                     bodies[body_offset + j].location[2], 
                                                     orientation[0], 
                                                     orientation[1], 
                                                     orientation[2], 
                                                     orientation[3]))
            body_offset += body_types[i]
      else:
        print 'Error, save_clones =', read.save_clones, 'is not implemented.'
        print 'Use \"one_file_per_step\" or \"one_file\". \n'
        break

  # Save final data if...
  if ((step+1) % read.n_save) == 0 and step >= 0:
    print 'MCMC, step = ', step+1, ', wallclock time = ', time.time() - start_time, ', acceptance ratio = ', accepted_moves / (step+2.0-read.initial_step)
    # For each type of structure save locations and orientations to one file
    body_offset = 0
    if read.save_clones == 'one_file_per_step':
      for i, ID in enumerate(read.structures_ID):
        name = read.output_name + '.' + ID + '.' + str(step+1).zfill(8) + '.clones'
        with open(name, 'w') as f_ID:
          f_ID.write(str(body_types[i]) + '\n')
          for j in range(body_types[i]):
            orientation = bodies[body_offset + j].orientation.entries
            f_ID.write('%s %s %s %s %s %s %s\n' % (bodies[body_offset + j].location[0], 
                                                   bodies[body_offset + j].location[1], 
                                                   bodies[body_offset + j].location[2], 
                                                   orientation[0], 
                                                   orientation[1], 
                                                   orientation[2], 
                                                   orientation[3]))
          body_offset += body_types[i]
      
    elif read.save_clones == 'one_file':
      for i, ID in enumerate(read.structures_ID):
        name = read.output_name + '.' + ID + '.config'
        if step+1 == 0:
          status = 'w'
        else:
          status = 'a'
        with open(name, status) as f_ID:
          f_ID.write(str(body_types[i]) + '\n')
          for j in range(body_types[i]):
            orientation = bodies[body_offset + j].orientation.entries
            f_ID.write('%s %s %s %s %s %s %s\n' % (bodies[body_offset + j].location[0], 
                                                   bodies[body_offset + j].location[1], 
                                                   bodies[body_offset + j].location[2], 
                                                   orientation[0], 
                                                   orientation[1], 
                                                   orientation[2], 
                                                   orientation[3]))
          body_offset += body_types[i]
    else:
      print 'Error, save_clones =', read.save_clones, 'is not implemented.'
      print 'Use \"one_file_per_step\" or \"one_file\". \n'



  end_time = time.time() - start_time
  print '\nacceptance ratio = ', accepted_moves / (step+2.0-read.initial_step)
  print 'accepted_moves = ', accepted_moves
  print 'Total time = ', end_time

  # Save wallclock time 
  with open(read.output_name + '.time', 'w') as f:
    f.write(str(time.time() - start_time) + '\n')
