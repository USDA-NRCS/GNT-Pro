from getpass import getuser
from os import path
from sys import exit
from time import ctime

from arcpy import AddFieldDelimiters, Describe, env, GetParameterAsText, SetProgressorLabel, SpatialReference
from arcpy.analysis import Buffer, Erase, Union
from arcpy.da import SearchCursor, UpdateCursor
from arcpy.management import CalculateGeometryAttributes, Compact, Dissolve, MakeFeatureLayer
from arcpy.mp import ArcGISProject, LayerFile

from utils import addLyrxByConnectionProperties, AddMsgAndPrint, deleteLayers, errorMsg


textFilePath = ''
def logBasicSettings(textFilePath, gnt_layer):
    with open(textFilePath, 'a+') as f:
        f.write('\n######################################################################\n')
        f.write('Executing Tool: Create Setback Buffers\n')
        f.write(f"User Name: {getuser()}\n")
        f.write(f"Date Executed: {ctime()}\n")
        f.write('User Parameters:\n')
        f.write(f"\tGNTFieldLayer: {gnt_layer}\n")


### Initial Tool Validation ###
try:
    aprx = ArcGISProject('CURRENT')
    map = aprx.listMaps('GNT Map')[0]
except:
    AddMsgAndPrint('This tool must be run from an ArcGIS Pro project that was developed from the template distributed with this toolbox. Exiting...', 2)
    exit()


### ESRI Environment Settings ###
mapSR = SpatialReference(map.spatialReference.factoryCode)
env.outputCoordinateSystem = mapSR
env.overwriteOutput = True


### Input Parameters ###
gnt_layer = GetParameterAsText(0)

# Get the basedataGDB_path from the input GNT layer
gnt_layer_path = Describe(gnt_layer).CatalogPath
if gnt_layer_path.find('.gdb') > 0 and gnt_layer_path.find('GNT') > 0 and gnt_layer_path.find('GNTFieldLayer') > 0:
    gntdataGDB_path = gnt_layer_path[:gnt_layer_path.find('.gdb')+4]
else:
    AddMsgAndPrint('\nSelected GNT Field layer is not from a GNT project folder. Exiting...', 2)
    exit()


### Define Local Variables ###
base_dir = path.abspath(path.dirname(__file__)) #\SUPPORT
support_gdb = path.join(base_dir, 'SUPPORT.gdb')
scratch_gdb = path.join(base_dir, 'scratch.gdb')

gntdataGDB_name = path.basename(gntdataGDB_path)
gntdataFD_name = 'Layers'
gntdataFD = path.join(gntdataGDB_path, gntdataFD_name)
userWorkspace = path.dirname(gntdataGDB_path)
projectName = path.basename(userWorkspace).replace(' ', '_')
textFilePath = path.join(userWorkspace, f"{projectName}_log.txt")

setback_point = path.join(gntdataFD, 'Setback_Point')
setback_line = path.join(gntdataFD, 'Setback_Line')
setback_polygon = path.join(gntdataFD, 'Setback_Polygon')
setback_buffer = path.join(gntdataFD, 'Setback_Buffer')
erased_fields = path.join(gntdataFD, 'GNTField_Erase')

point_buffer_temp = path.join(scratch_gdb, 'point_buffer_temp')
line_left_temp = path.join(scratch_gdb, 'line_left_buffer')
line_right_temp = path.join(scratch_gdb, 'line_right_buffer')
line_both_temp = path.join(scratch_gdb, 'line_both_buffer')
polygon_buffer_temp = path.join(scratch_gdb, 'polygon_buffer_temp')
final_buffer_temp = path.join(scratch_gdb, 'final_buffer_temp')

deleteLayers([point_buffer_temp, line_left_temp, line_right_temp, line_both_temp, polygon_buffer_temp, final_buffer_temp])

setback_buffer_lyrx = LayerFile(path.join(path.join(base_dir, 'LayerFiles'), 'Setback_Buffer.lyrx')).listLayers()[0]
gntfield_final_lyrx = LayerFile(path.join(path.join(base_dir, 'LayerFiles'), 'GNTFieldLayer_Final.lyrx')).listLayers()[0]


try:
    logBasicSettings(textFilePath, gnt_layer)

    ### Setback Points ###
    SetProgressorLabel('Buffering Setback Point features...')
    # Update Text BufferField with Feet
    with UpdateCursor(setback_point, ['BufferDistance', 'BufferField']) as cursor:
        for row in cursor:
            row[1] = f"{row[0]} Feet"
            cursor.updateRow(row)

    Buffer(setback_point, point_buffer_temp, 'BufferField', dissolve_option='ALL')
    AddMsgAndPrint('\nCreated Setback Point buffer...', textFilePath=textFilePath)


    ### Setback Lines ###
    SetProgressorLabel('Buffering Setback Line features...')
    # Update Text BufferField with Feet
    with UpdateCursor(setback_line, ['BufferDistance', 'BufferField']) as cursor:
        for row in cursor:
            row[1] = f"{row[0]} Feet"
            cursor.updateRow(row)
    
    # Buffer Line Subsets by Side
    where_left = """{0}='{1}'""".format(AddFieldDelimiters(gntdataGDB_path, 'BufferSides'), 'Left Side')
    MakeFeatureLayer(setback_line, 'line_left', where_left)
    Buffer('line_left', line_left_temp, 'BufferField', 'LEFT', dissolve_option='ALL')
    AddMsgAndPrint('\nCreated Setback Line Left buffer...', textFilePath=textFilePath)

    where_right = """{0}='{1}'""".format(AddFieldDelimiters(gntdataGDB_path, 'BufferSides'), 'Right Side')
    MakeFeatureLayer(setback_line, 'line_right', where_right)
    Buffer('line_right', line_right_temp, 'BufferField', 'RIGHT', dissolve_option='ALL')
    AddMsgAndPrint('\nCreated Setback Line Right buffer...', textFilePath=textFilePath)

    where_both = """{0}='{1}'""".format(AddFieldDelimiters(gntdataGDB_path, 'BufferSides'), 'Both Sides')
    MakeFeatureLayer(setback_line, 'line_both', where_both)
    Buffer('line_both', line_both_temp, 'BufferField', dissolve_option='ALL')
    AddMsgAndPrint('\nCreated Setback Line Both buffer...', textFilePath=textFilePath)


    ### Setback Polygons ###
    SetProgressorLabel('Buffering Setback Polygon features...')
    # Update Text BufferField with Feet
    with UpdateCursor(setback_polygon, ['BufferDistance', 'BufferField']) as cursor:
        for row in cursor:
            row[1] = f"{row[0]} Feet"
            cursor.updateRow(row)

    Buffer(setback_polygon, polygon_buffer_temp, 'BufferField', dissolve_option='ALL')
    AddMsgAndPrint('\nCreated Setback Polygon buffer...', textFilePath=textFilePath)


    ### Union and Dissolve Buffers to Create Final Setback Layer ###
    SetProgressorLabel('Creating final Setback Buffer layer...')
    Union([point_buffer_temp, line_left_temp, line_right_temp, line_both_temp, polygon_buffer_temp], final_buffer_temp)
    Dissolve(final_buffer_temp, setback_buffer)
    AddMsgAndPrint('\nCreated Final Setback buffer...', textFilePath=textFilePath)


    ### Erase Setback Buffers from GNT Fields and Calculate Spreadable Acres ###
    SetProgressorLabel('Calculating Spreadable Acres...')
    Erase(gnt_layer, setback_buffer, erased_fields)
    CalculateGeometryAttributes(erased_fields, [['SpreadSize', 'AREA_GEODESIC']], area_unit='ACRES')

    spreadable = {}
    fields = ['LandIDGUID', 'SpreadSize']
    
    with SearchCursor(erased_fields, fields) as cursor:
        for row in cursor:
            spreadable[row[0]] = row[1] #round(row[1], 1)

    with UpdateCursor(gnt_layer, fields) as cursor:
        for row in cursor:
            try:
                row[1] = spreadable[row[0]]
            except KeyError:
                row[1] = 0.0
            cursor.updateRow(row)

    AddMsgAndPrint('\nCalculated Spreadable Acres...', textFilePath=textFilePath)


    ### Adjust Final Map Layers ###
    for lyr in map.listLayers():
        if lyr.name == 'GNTFieldLayer':
            map.removeLayer(lyr)

    lyr_name_list = [lyr.longName for lyr in map.listLayers()]
    addLyrxByConnectionProperties(map, lyr_name_list, gntfield_final_lyrx, gntdataGDB_path)
    addLyrxByConnectionProperties(map, lyr_name_list, setback_buffer_lyrx, gntdataGDB_path)

    for lyr in map.listLayers():
        if lyr.name == 'Setback_Point':
            lyr.visible = False
        if lyr.name == 'Setback_Line':
            lyr.visible = False
        if lyr.name == 'Setback_Polygon':
            lyr.visible = False


    SetProgressorLabel('Cleaning up temp layers...')
    deleteLayers([point_buffer_temp, line_left_temp, line_right_temp, line_both_temp, polygon_buffer_temp, final_buffer_temp])

    ### Compact Geodatabase ###
    try:
        AddMsgAndPrint('\nCompacting File Geodatabase...', textFilePath=textFilePath)
        SetProgressorLabel('Compacting File Geodatabase...')
        Compact(gntdataGDB_path)
    except:
        pass


    # ### Open Layout View and Zoom to Site ### BUG: Does not work
    # layout = aprx.listLayouts()[0]
    # map_frame = layout.listElements('MAPFRAME_ELEMENT', 'Map Frame')[0]
    # lyr = map.listLayers('Setback_Buffer')[0]
    # lyr_extent = map_frame.getLayerExtent(lyr)
    # camera = map_frame.camera
    # camera.setExtent(lyr_extent)
    # camera.scale = camera.scale*1.25 if camera.scale > 3960 else 3960
    # layout.openView()

    AddMsgAndPrint('\nScript completed successfully', textFilePath=textFilePath)

except SystemExit:
    pass

except:
    try:
        AddMsgAndPrint(errorMsg('Create Setback Buffers'), 2, textFilePath)
    except FileNotFoundError:
        AddMsgAndPrint(errorMsg('Create Setback Buffers'), 2)
