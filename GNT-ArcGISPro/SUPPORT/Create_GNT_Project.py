from datetime import datetime
from getpass import getuser
from os import mkdir, path
from sys import argv, exit
from time import ctime

from arcpy import AddFieldDelimiters, env, Exists, GetParameterAsText, SetProgressorLabel, SpatialReference
from arcpy.conversion import FeatureClassToFeatureClass
from arcpy.da import InsertCursor, SearchCursor, UpdateCursor
from arcpy.management import Append, Compact, CreateFeatureDataset, CreateFileGDB, CreateTable, \
    DeleteRows, GetCount, ImportContingentValues
from arcpy.mp import ArcGISProject, LayerFile

from utils import addLyrxByConnectionProperties, AddMsgAndPrint, errorMsg


textFilePath = ''
def logBasicSettings(textFilePath, state, county, farm):
    with open(textFilePath, 'a+') as f:
        f.write('\n######################################################################\n')
        f.write('Executing Tool: Create GNT Project\n')
        f.write(f"User Name: {getuser()}\n")
        f.write(f"Date Executed: {ctime()}\n")
        f.write('User Parameters:\n')
        # f.write(f"\tProject Type: {project_type}\n")
        f.write(f"\tAdmin State: {state}\n")
        f.write(f"\tAdmin County: {county}\n")
        f.write(f"\tFarm: {str(farm)}\n")


### Initial Tool Validation ###
try:
    aprx = ArcGISProject('CURRENT')
    map = aprx.listMaps('GNT Map')[0]
except:
    AddMsgAndPrint('This tool must be run from an ArcGIS Pro project that was developed from the template distributed with this toolbox. Exiting...', 2)
    exit()

lut = path.join(path.dirname(argv[0]), 'SUPPORT.gdb', 'lut_census_fips')
if not Exists(lut):
    AddMsgAndPrint('Could not find state and county lookup table. Exiting...', 2)
    exit()


### Validate Spatial Reference ###
mapSR = map.spatialReference
if mapSR.type != 'Projected':
    AddMsgAndPrint('\nThe Determinations map is not set to a Projected coordinate system.', 2)
    AddMsgAndPrint('\nPlease assign a WGS 1984 UTM coordinate system to the Determinations map that is appropriate for your site.', 2)
    AddMsgAndPrint('\nThese systems are found in the Determinations Map Properties under: Coordinate Systems -> Projected Coordinate System -> UTM -> WGS 1984.', 2)
    AddMsgAndPrint('\nAfter applying a coordinate system, save your template and try this tool again.', 2)
    AddMsgAndPrint('\nExiting...', 2)
    exit()

if 'WGS' not in mapSR.name or '1984' not in mapSR.name or 'UTM' not in mapSR.name:
    AddMsgAndPrint('\nThe Determinations map is not using a UTM coordinate system tied to WGS 1984.', 2)
    AddMsgAndPrint('\nPlease assign a WGS 1984 UTM coordinate system to the Determinations map that is appropriate for your site.', 2)
    AddMsgAndPrint('\nThese systems are found in the Determinations Map Properties under: Coordinate Systems -> Projected Coordinate System -> UTM -> WGS 1984.', 2)
    AddMsgAndPrint('\nAfter applying a coordinate system, save your template and try this tool again.', 2)
    AddMsgAndPrint('\nExiting...', 2)
    exit()


### ESRI Environment Settings ###
mapSR = SpatialReference(mapSR.factoryCode)
env.outputCoordinateSystem = mapSR
env.overwriteOutput = True


### Input Parameters ###
# project_type = GetParameterAsText(0)
# existing_folder = GetParameterAsText(1)
crop_layer = GetParameterAsText(0)
state = GetParameterAsText(1)
county = GetParameterAsText(2)
farm = GetParameterAsText(3)
op_name = GetParameterAsText(4)
street = GetParameterAsText(5)
city = GetParameterAsText(6)
zipcode = GetParameterAsText(7)
contact_name = GetParameterAsText(8)
office_phone = GetParameterAsText(9)
home_phone = GetParameterAsText(10)
email = GetParameterAsText(11)
notes = GetParameterAsText(12)
start_year = GetParameterAsText(13)
start_month = GetParameterAsText(14)
plan_years = GetParameterAsText(15)

# Convert start month to number
months = {'January': 1, 'February': 2, 'March': 3, 'April': 4, 'May': 5, 'June': 6, 'July': 7, 'August': 8, 'September': 9, 'October': 10, 'November': 11, 'December': 12}
start_month = str(months[start_month])


try:
    workspacePath = 'C:\GNT'
    # Check Inputs for existence and create FIPS code variables
    # Search for FIPS codes to give to the Extract CLU Tool/Function. Break after the first row (should only find one row in any case).
    # Temporarily adjust source county to handle apostrophes in relation to searching
    county = county.replace("'", "''")
    stfip, cofip = '', ''
    fields = ['STATEFP','COUNTYFP','NAME','STATE','STPOSTAL']
    expression = "{} = '{}'".format(AddFieldDelimiters(lut,fields[3]), state) + " AND " + "{} = '{}'".format(AddFieldDelimiters(lut,fields[2]), county)
    with SearchCursor(lut, fields, where_clause = expression) as cursor:
        for row in cursor:
            stfip = row[0]
            cofip = row[1]
            adStatePostal = row[4]
            break

    if len(stfip) != 2 and len(cofip) != 3:
        AddMsgAndPrint('State and County FIPS codes could not be retrieved! Exiting...', 2)
        exit()

    if adStatePostal == '':
        AddMsgAndPrint('State postal code could not be retrieved! Exiting...', 2)
        exit()

    # Change sourceCounty back to handle apostrophes
    sourceCounty = county.replace("''", "'")
        
    # Transfer found values to variables to use for project creation
    adminState = stfip
    adminCounty = cofip
    postal = adStatePostal.lower()

    # Get the current year and month for use in project naming
    year = str(datetime.now().year)
    month = str(datetime.now().month)

    # Refine the tract number and month number to be padded with zeros to create uniform length of project name
    source_farm = str(farm)
    farm_length = len(source_farm)
    if farm_length < 7:
        addzeros = 7 - farm_length
        farm_name = '0'*addzeros + str(source_farm)
    else:
        farm_name = source_farm

    monthlength = len(month)
    if monthlength < 2:
        finalmonth = '0' + month
    else:
        finalmonth = month

    # Build project folder path
    # if project_type == 'New':
    projectFolder = path.join(workspacePath, f"{postal}{adminCounty}_{farm_name}_{year}_{finalmonth}")
    # else:
    #     # Get project folder path from user input. Validation was done during script validations on the input
    #     if existing_folder != '':
    #         projectFolder = existing_folder
    #     else:
    #         AddMsgAndPrint('Project type was specified as Existing, but no existing project folder was selected. Exiting...', 2)
    #         exit()


    ### Set Additional Local Variables ###
    projectName = path.basename(projectFolder)
    textFilePath = path.join(projectFolder, f"{projectName}_log.txt")
    reports_folder = path.join(projectFolder, 'CNMP_Reports')
    gntdataGDB_name = path.basename(projectFolder).replace(' ','_') + '_GNTData.gdb'
    gntdataGDB_path = path.join(projectFolder, gntdataGDB_name)
    userWorkspace = path.dirname(gntdataGDB_path)
    basedataFD = path.join(gntdataGDB_path, 'Layers')
    admin_table = path.join(gntdataGDB_path, 'Admin_Table')
    
    template_table = path.join(path.dirname(argv[0]), path.join('SUPPORT.gdb', 'Admin_Table_Template'))
    template_gnt = path.join(path.dirname(argv[0]), path.join('SUPPORT.gdb', 'GNTFieldLayer_Template'))
    template_point = path.join(path.dirname(argv[0]), path.join('SUPPORT.gdb', 'Setback_Point_Template'))
    template_line = path.join(path.dirname(argv[0]), path.join('SUPPORT.gdb', 'Setback_Line_Template'))
    template_polygon = path.join(path.dirname(argv[0]), path.join('SUPPORT.gdb', 'Setback_Polygon_Template'))
    
    gntfield_name = 'GNTFieldLayer'
    gntfield_path = path.join(basedataFD, gntfield_name)
    setback_point_name = 'Setback_Point'
    setback_point_path = path.join(basedataFD, setback_point_name)
    setback_line_name = 'Setback_Line'
    setback_line_path = path.join(basedataFD, setback_line_name)
    setback_polygon_name = 'Setback_Polygon'
    setback_polygon_path = path.join(basedataFD, setback_polygon_name)

    gntfield_lyrx = LayerFile(path.join(path.join(path.dirname(argv[0]), 'LayerFiles'), 'GNTFieldLayer.lyrx')).listLayers()[0]
    setback_point_lyrx = LayerFile(path.join(path.join(path.dirname(argv[0]), 'LayerFiles'), 'Setback_Point.lyrx')).listLayers()[0]
    setback_line_lyrx = LayerFile(path.join(path.join(path.dirname(argv[0]), 'LayerFiles'), 'Setback_Line.lyrx')).listLayers()[0]
    setback_polygon_lyrx = LayerFile(path.join(path.join(path.dirname(argv[0]), 'LayerFiles'), 'Setback_Polygon.lyrx')).listLayers()[0]

    point_FG_CSV = path.join(path.join(path.dirname(argv[0]), 'SetbackFeatureTypes'), 'Point_FieldGroup.csv')
    point_CV_CSV = path.join(path.join(path.dirname(argv[0]), 'SetbackFeatureTypes'), 'Point_ContingentValue.csv')
    line_FG_CSV = path.join(path.join(path.dirname(argv[0]), 'SetbackFeatureTypes'), 'Line_FieldGroup.csv')
    line_CV_CSV = path.join(path.join(path.dirname(argv[0]), 'SetbackFeatureTypes'), 'Line_ContingentValue.csv')
    polygon_FG_CSV = path.join(path.join(path.dirname(argv[0]), 'SetbackFeatureTypes'), 'Polygon_FieldGroup.csv')
    polygon_CV_CSV = path.join(path.join(path.dirname(argv[0]), 'SetbackFeatureTypes'), 'Polygon_ContingentValue.csv')


    ### Create Project Folders and Contents ###
    AddMsgAndPrint('\nChecking project directories...')
    SetProgressorLabel('Checking project directories...')
    if not path.exists(workspacePath):
        try:
            SetProgressorLabel('Creating GNT folder...')
            mkdir(workspacePath)
            AddMsgAndPrint('\nThe GNT folder did not exist on the C: drive and has been created.')
        except:
            AddMsgAndPrint('\nThe GNT folder cannot be created. Please check your permissions to the C: drive. Exiting...\n', 2)
            exit()

    if not path.exists(projectFolder):
        try:
            SetProgressorLabel('Creating project folder...')
            mkdir(projectFolder)
            AddMsgAndPrint('\nThe project folder has been created within C:\GNT')
        except:
            AddMsgAndPrint('\nThe project folder cannot be created. Please check your permissions to C:\GNT. Exiting...\n', 2)
            exit()

    # Start logging to text file after project folder exists
    logBasicSettings(textFilePath, state, sourceCounty, farm)

    SetProgressorLabel('Creating project contents...')
    if not path.exists(reports_folder):
        try:
            SetProgressorLabel('Creating reports folder...')
            mkdir(reports_folder)
            AddMsgAndPrint(f"\nThe reports folder has been created within {projectFolder}", textFilePath=textFilePath)
        except:
            AddMsgAndPrint('\nCould not access C:\GNT. Check your permissions for C:\GNT. Exiting...\n', 2, textFilePath)
            exit()

    if not Exists(gntdataGDB_path):
        AddMsgAndPrint('\nCreating Base Data geodatabase...', textFilePath=textFilePath)
        SetProgressorLabel('Creating Base Data geodatabase...')
        CreateFileGDB(projectFolder, gntdataGDB_name)

    if not Exists(basedataFD):
        AddMsgAndPrint('\nCreating Base Data feature dataset...', textFilePath=textFilePath)
        SetProgressorLabel('Creating Base Date feature dataset...')
        CreateFeatureDataset(gntdataGDB_path, 'Layers', mapSR)


    ### Create Admin Table ###
    if Exists(admin_table):
        SetProgressorLabel('Located project Admin Table...')
        recordsCount = int(GetCount(admin_table)[0])
        if recordsCount > 0:
            DeleteRows(admin_table)
            AddMsgAndPrint('\nCleared existing rows from project Admin Table...', textFilePath=textFilePath)
    else:
        SetProgressorLabel('Creating Admin Table...')
        CreateTable(gntdataGDB_path, 'Admin_Table', template_table)
        AddMsgAndPrint('\nCreated Admin Table...', textFilePath=textFilePath)


    ### Populate Admin Table Row ###
    AddMsgAndPrint('\nUpdating Admin Table...', textFilePath=textFilePath)
    SetProgressorLabel('Updating Admin Table...')
    field_names = ['state_code','state','state_name','county_code','county_name','farm_number','operation_name','street','city',
                   'zip','contact_name','office_phone','home_phone','email','notes','start_year','start_month','plan_years']
    row = (stfip, postal, state, cofip, county, farm, op_name, street, city, zipcode, contact_name, office_phone, home_phone,
           email, notes, start_year, start_month, plan_years)
    with InsertCursor(admin_table, field_names) as cursor:
        cursor.insertRow(row)


    ### Create Setbacks and GNT Layers in Project GDB ###
    AddMsgAndPrint('\nCreating Setback Layers in project geodatabase...', textFilePath=textFilePath)
    SetProgressorLabel('Creating Setback Layers in project geodatabase...')
    FeatureClassToFeatureClass(template_point, basedataFD, setback_point_name)
    FeatureClassToFeatureClass(template_line, basedataFD, setback_line_name)
    FeatureClassToFeatureClass(template_polygon, basedataFD, setback_polygon_name)

    AddMsgAndPrint('\nCreating GNT Field Layer in project geodatabase...', textFilePath=textFilePath)
    SetProgressorLabel('Creating GNT Field Layer in project geodatabase...')
    FeatureClassToFeatureClass(template_gnt, basedataFD, 'GNTFieldLayer')
    Append(crop_layer, gntfield_path, 'NO_TEST', field_mapping=
           r'LandIDGUID "LandIDGUID" true true false 40 Text 0 0,First,#,case_plus,plu_id,-1,-1;' +
           r'ID "ID" true true false 15 Text 0 0,First,#,case_plus,tract,-1,-1;' +
           r'SubID "SubID" true true false 5 Text 0 0,First,#,case_plus,plu_number,0,254;' +
           r'Size "Size" true true false 8 Double 0 0,First,#,case_plus,calc_acres,-1,-1;' +
           r'FSATract "FSATract" true true false 4 Long 0 0,First,#,case_plus,tract,-1,-1;' +
           r'FSAField "FSAField" true true false 4 Long 0 0,First,#,case_plus,plu_number,0,254;' +
           r'LandUseIdText "LandUseIdText" true true false 35 Text 0 0,First,#,case_plus,land_use,0,254')

    # Add FarmID value to GNTFieldLayer
    with UpdateCursor(gntfield_path, ['FarmID']) as cur:
        for row in cur:
            row[0] = farm
            cur.updateRow(row)


    ### Import Contingent Values to Project GDB ###
    ImportContingentValues(setback_point_path, point_FG_CSV, point_CV_CSV, 'REPLACE')
    ImportContingentValues(setback_line_path, line_FG_CSV, line_CV_CSV, 'REPLACE')
    ImportContingentValues(setback_polygon_path, polygon_FG_CSV, polygon_CV_CSV, 'REPLACE')


    ### Remove Existing CLU Layers From Map ###
    AddMsgAndPrint('\nRemoving GNT Field and Setback layers from project map, if present...', textFilePath=textFilePath)
    SetProgressorLabel('Removing GNT Field and Setback layers from project map, if present...')
    mapLayersToRemove = [gntfield_name, setback_point_name, setback_line_name, setback_polygon_name]
    try:
        for maps in aprx.listMaps():
            for lyr in maps.listLayers():
                if lyr.longName in mapLayersToRemove:
                    maps.removeLayer(lyr)
    except:
        pass


    ### Add GNTFieldLayer and Setback Layers to Map ###
    lyr_name_list = [lyr.longName for lyr in map.listLayers()]
    addLyrxByConnectionProperties(map, lyr_name_list, gntfield_lyrx, gntdataGDB_path)
    addLyrxByConnectionProperties(map, lyr_name_list, setback_point_lyrx, gntdataGDB_path)
    addLyrxByConnectionProperties(map, lyr_name_list, setback_line_lyrx, gntdataGDB_path)
    addLyrxByConnectionProperties(map, lyr_name_list, setback_polygon_lyrx, gntdataGDB_path)

    # Close and Reopen Map - BUG: Pro says setback layers are not editable
    aprx.closeViews()
    map.openView()


    ### Compact Geodatabase ###
    try:
        AddMsgAndPrint('\nCompacting File Geodatabase...', textFilePath=textFilePath)
        SetProgressorLabel('Compacting File Geodatabase...')
        Compact(gntdataGDB_path)
    except:
        pass

    AddMsgAndPrint('\nScript completed successfully', textFilePath=textFilePath)

except SystemExit:
    pass

except:
    try:
        AddMsgAndPrint(errorMsg('Create GNT Project'), 2, textFilePath)
    except FileNotFoundError:
        AddMsgAndPrint(errorMsg('Create GNT Project'), 2)
