from __future__ import division, print_function
import unittest
import numpy as np

from openaerostruct.geometry.utils import generate_mesh
from openaerostruct.geometry.geometry_group import Geometry

from openaerostruct.integration.aerostruct_groups import Aerostruct, AerostructPoint

from openmdao.api import IndepVarComp, Problem, Group, NewtonSolver, ScipyIterativeSolver, LinearBlockGS, NonlinearBlockGS, DirectSolver, DenseJacobian, LinearBlockGS, PetscKSP, ScipyOptimizer, LinearRunOnce

try:
    from openaerostruct.fortran import OAS_API
    fortran_flag = True
    data_type = float
except:
    fortran_flag = False
    data_type = complex

@unittest.skipUnless(fortran_flag, "Fortran is required.")
class Benchmarks(unittest.TestCase):

    def benchmark_om(self):
        # Create a dictionary to store options about the surface
        # OM: vary 'num_y' and 'num_x' to change the size of the mesh
        mesh_dict = {'num_y' : 5,
                     'num_x' : 2,
                     'wing_type' : 'rect',
                     'symmetry' : True}

        mesh = generate_mesh(mesh_dict)

        surf_dict = {
                    # Wing definition
                    'name' : 'wing',        # name of the surface
                    'type' : 'aerostruct',
                    'symmetry' : True,     # if true, model one half of wing
                                            # reflected across the plane y = 0
                    'S_ref_type' : 'wetted', # how we compute the wing area,
                                             # can be 'wetted' or 'projected'

                    'thickness_cp' : np.array([.075, .075]),
                    'twist_cp' : np.array([-10., 15.]),

                    'mesh' : mesh,
                    'num_x' : mesh.shape[0],
                    'num_y' : mesh.shape[1],

                    # Aerodynamic performance of the lifting surface at
                    # an angle of attack of 0 (alpha=0).
                    # These CL0 and CD0 values are added to the CL and CD
                    # obtained from aerodynamic analysis of the surface to get
                    # the total CL and CD.
                    # These CL0 and CD0 values do not vary wrt alpha.
                    'CL0' : 0.0,            # CL of the surface at alpha=0
                    'CD0' : 0.015,            # CD of the surface at alpha=0

                    # Airfoil properties for viscous drag calculation
                    'k_lam' : 0.05,         # percentage of chord with laminar
                                            # flow, used for viscous drag
                    't_over_c' : 0.15,      # thickness over chord ratio (NACA0015)
                    'c_max_t' : .303,       # chordwise location of maximum (NACA0015)
                                            # thickness
                    'with_viscous' : True,

                    # Structural values are based on aluminum 7075
                    'E' : 70.e9,            # [Pa] Young's modulus of the spar
                    'G' : 30.e9,            # [Pa] shear modulus of the spar
                    'yield' : 500.e6 / 2.5, # [Pa] yield stress divided by 2.5 for limiting case
                    'mrho' : 3.e3,          # [kg/m^3] material density
                    'fem_origin' : 0.35,    # normalized chordwise location of the spar
                    'wing_weight_ratio' : 2.,

                    # Constraints
                    'exact_failure_constraint' : False, # if false, use KS function
                    }

        surfaces = [surf_dict]

        # Create the problem and assign the model group
        prob = Problem()

        # Add problem information as an independent variables component
        indep_var_comp = IndepVarComp()
        indep_var_comp.add_output('v', val=248.136, units='m/s')
        indep_var_comp.add_output('alpha', val=9.)
        indep_var_comp.add_output('M', val=0.84)
        indep_var_comp.add_output('re', val=1.e6, units='1/m')
        indep_var_comp.add_output('rho', val=0.38, units='kg/m**3')
        indep_var_comp.add_output('CT', val=9.80665 * 17.e-6, units='1/s')
        indep_var_comp.add_output('R', val=11.165e6, units='m')
        indep_var_comp.add_output('W0', val=0.4 * 3e5,  units='kg')
        indep_var_comp.add_output('a', val=295.4, units='m/s')
        indep_var_comp.add_output('load_factor', val=1.)
        indep_var_comp.add_output('empty_cg', val=np.zeros((3)), units='m')

        prob.model.add_subsystem('prob_vars',
             indep_var_comp,
             promotes=['*'])

        # Loop over each surface in the surfaces list
        for surface in surfaces:

            # Get the surface name and create a group to contain components
            # only for this surface
            name = surface['name']

            aerostruct_group = Aerostruct(surface=surface)

            # Add tmp_group to the problem with the name of the surface.
            prob.model.add_subsystem(name, aerostruct_group)

        # Loop through and add a certain number of aero points
        for i in range(1):

            point_name = 'AS_point_{}'.format(i)
            # Connect the parameters within the model for each aero point

            # Create the aero point group and add it to the model
            AS_point = AerostructPoint(surfaces=surfaces)

            coupled = AS_point.get_subsystem('coupled')
            prob.model.add_subsystem(point_name, AS_point)

            # Connect flow properties to the analysis point
            prob.model.connect('v', point_name + '.v')
            prob.model.connect('alpha', point_name + '.alpha')
            prob.model.connect('M', point_name + '.M')
            prob.model.connect('re', point_name + '.re')
            prob.model.connect('rho', point_name + '.rho')
            prob.model.connect('CT', point_name + '.CT')
            prob.model.connect('R', point_name + '.R')
            prob.model.connect('W0', point_name + '.W0')
            prob.model.connect('a', point_name + '.a')
            prob.model.connect('empty_cg', point_name + '.empty_cg')
            prob.model.connect('load_factor', point_name + '.load_factor')

            for surface in surfaces:

                prob.model.connect('load_factor', name + '.load_factor')

                com_name = point_name + '.' + name + '_perf'
                prob.model.connect(name + '.K', point_name + '.coupled.' + name + '.K')

                # Connect aerodyamic mesh to coupled group mesh
                prob.model.connect(name + '.mesh', point_name + '.coupled.' + name + '.mesh')
                prob.model.connect(name + '.element_weights', point_name + '.coupled.' + name + '.element_weights')

                # Connect performance calculation variables
                prob.model.connect(name + '.radius', com_name + '.radius')
                prob.model.connect(name + '.thickness', com_name + '.thickness')
                prob.model.connect(name + '.nodes', com_name + '.nodes')
                prob.model.connect(name + '.cg_location', point_name + '.' + 'total_perf.' + name + '_cg_location')
                prob.model.connect(name + '.structural_weight', point_name + '.' + 'total_perf.' + name + '_structural_weight')

        try:
            from openmdao.api import pyOptSparseDriver
            prob.driver = pyOptSparseDriver()
            prob.driver.options['optimizer'] = "SNOPT"
            prob.driver.opt_settings = {'Major optimality tolerance': 1.0e-8,
                                        'Major feasibility tolerance': 1.0e-8}
        except:
            from openmdao.api import ScipyOptimizer
            prob.driver = ScipyOptimizer()
            prob.driver.options['tol'] = 1e-9

        # Setup problem and add design variables, constraint, and objective
        prob.model.add_design_var('wing.twist_cp', lower=-10., upper=15.)
        prob.model.add_design_var('wing.thickness_cp', lower=0.01, upper=0.5, scaler=1e2)
        prob.model.add_constraint('AS_point_0.wing_perf.failure', upper=0.)
        prob.model.add_constraint('AS_point_0.wing_perf.thickness_intersects', upper=0.)

        # Add design variables, constraisnt, and objective on the problem
        prob.model.add_design_var('alpha', lower=-10., upper=10.)
        prob.model.add_constraint('AS_point_0.L_equals_W', equals=0.)
        prob.model.add_objective('AS_point_0.fuelburn', scaler=1e-5)

        # Set up the problem
        prob.setup()

        """
        # OM: Change the solver settings here ###
        """

        # Set linear solver properties for the coupled group
        # prob.model.AS_point_0.coupled.linear_solver = ScipyIterativeSolver()
        # prob.model.AS_point_0.coupled.linear_solver.precon = LinearRunOnce()

        # prob.model.AS_point_0.coupled.linear_solver = PetscKSP()

        prob.model.AS_point_0.coupled.jacobian = DenseJacobian()
        prob.model.AS_point_0.coupled.linear_solver = DirectSolver()

        # Set nonlinear solver properties
        prob.model.AS_point_0.coupled.nonlinear_solver = NonlinearBlockGS()

        # prob.model.AS_point_0.coupled.nonlinear_solver = NewtonSolver(solve_subsystems=True)


        prob.model.AS_point_0.coupled.nonlinear_solver.options['maxiter'] = 20
        prob.model.AS_point_0.coupled.nonlinear_solver.options['iprint'] = 2

        # This takes a long, long time to run (~600 secs vs 6 secs without)
        # prob.model.approx_total_derivs(method='fd', step_calc='rel')

        """
        ### End change of solver settings ###
        """

        prob.run_driver()

        self.assertAlmostEqual(prob['AS_point_0.fuelburn'][0], 74283.180227023186, places=3)


if __name__ == '__main__':
    unittest.main()
