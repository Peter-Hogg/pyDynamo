import pydynamo_brain.files as files

def run(path='data/swcTest/7f_ss_cell1_step0_av2.tif_x122_y34_z26_app2.swc'):
    tree = files.importFromSWC(path)
    # TODO - verify tree struture
    return True
