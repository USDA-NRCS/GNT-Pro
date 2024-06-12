from datetime import datetime
from decimal import Decimal
from getpass import getuser
from jinja2 import Environment, FileSystemLoader
from os import listdir, path, startfile
from sys import exit
from time import ctime

from arcpy import Describe, env, GetParameterAsText, SetProgressorLabel
from arcpy.da import SearchCursor
from arcpy.mp import ArcGISProject

from utils import AddMsgAndPrint, errorMsg


textFilePath = ''
def logBasicSettings(textFilePath, gnt_layer):
    with open(textFilePath, 'a+') as f:
        f.write('\n######################################################################\n')
        f.write('Executing Tool: Create MMP File\n')
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
run_date = datetime.today().strftime('%Y-%m-%d')
run_time = datetime.today().strftime('%H:%M:%S')
base_dir = path.abspath(path.dirname(__file__)) #\SUPPORT
userWorkspace = path.dirname(gntdataGDB_path)
projectName = path.basename(userWorkspace).replace(' ', '_')
adminTable = path.join(gntdataGDB_path, 'Admin_Table')
textFilePath = path.join(userWorkspace, f"{projectName}_log.txt")
outputMMPFile = path.join(userWorkspace, 'CNMP_Reports', f"{projectName}.mmp")


try:
    logBasicSettings(textFilePath, gnt_layer)

    ### Read Data from Admin Table ###
    SetProgressorLabel('Reading data from project Admin Table...')
    AddMsgAndPrint('\nReading data from project Admin Table...', textFilePath=textFilePath)
    admin_data = {}
    fields = ['operation_name', 'street', 'city', 'state', 'zip', 'contact_name', 'office_phone', 'home_phone', 'email', 'notes', 'county_code', 'start_year', 'start_month', 'plan_years']
    with SearchCursor(adminTable, fields) as cursor:
        row = cursor.next()
        admin_data['Operation'] = row[0] if row[0] else ''
        admin_data['Address'] = row[1] if row[1] else ''
        admin_data['Town'] = row[2] if row[2] else ''
        admin_data['State'] = row[3] if row[3] else ''
        admin_data['Zip'] = row[4] if row[4] else ''
        admin_data['Contact'] = row[5] if row[5] else ''
        admin_data['OffPhone'] = row[6] if row[6] else ''
        admin_data['HomePhone'] = row[7] if row[7] else ''
        admin_data['EMail'] = row[8] if row[8] else ''
        admin_data['Notes'] = row[9] if row[9] else ''
        admin_data['CntyCode'] = str(int(row[10])) if row[10] else '' #str(int()) removes leading zeros
        admin_data['StartPlnYr'] = row[11] if row[11] else ''
        admin_data['StartPlnMo'] = row[12] if row[12] else ''
        admin_data['PlanYears'] = row[13] if row[13] else ''

    ### Read Data from GNTFieldLayer ###
    SetProgressorLabel('Reading data from project GNTFieldLayer...')
    AddMsgAndPrint('\nReading data from project GNTFieldLayer...', textFilePath=textFilePath)
    gnt_fields = {}
    fields = ['ID', 'SubID', 'Size', 'SpreadSize', 'SoilKey', 'FarmID', 'FSAFarm', 'FSATract', 'FSAField']
    i = 1
    with SearchCursor(gnt_layer, fields) as cursor:
        for row in cursor:
            try:
                size = Decimal(str(row[2]))
                spread_size = Decimal(str(row[3]))
            except Exception:
                AddMsgAndPrint('There is a problem with either Size or SpreadSize for one or more Fields. Exiting...', 2, textFilePath)
                exit()
            gnt_fields[i] = {
                fields[0]: row[0] if row[0] else '',
                fields[1]: row[1] if row[1] else '',
                fields[2]: round(size, 1) if row[2] else '',
                fields[3]: round(spread_size, 1) if row[3] else '', #NOTE: MMP throws error if SpreadSize is 0. It says must be greater than 0.1, but what if entire field is not spreadable?
                fields[4]: f"{row[4]}_1" if row[4] else '', #NOTE: ArcMap tool is hardcoding _1, but some of the .mms files have other numbers?
                fields[5]: row[5] if row[5] else '',
                fields[6]: row[6] if row[6] else '',
                fields[7]: row[7] if row[7] else '',
                fields[8]: row[8] if row[8] else ''
            }
            i += 1

    ### Retrive Info From MMP Install Location ###
    mmp_version = None
    mmp_folder = None
    install_folder = r'C:\Program Files (x86)\USDA'
    for folder in listdir(install_folder):
        if 'MMP' in folder:
            mmp_version = folder
            mmp_folder = path.join(install_folder, folder)
    
    if mmp_version is None or mmp_folder is None:
        AddMsgAndPrint(f"Failed to locate MMP software install location. Expected to be in {install_folder}. Exiting...", 2, textFilePath)
        exit()
    
    # Locate state specific mmi and mms files and get RevDate values
    mmi_file = path.join(mmp_folder, 'Lookup', f"{admin_data['State']}.mmi")
    mms_file = path.join(mmp_folder, 'Lookup', f"{admin_data['State']}.mms")

    if not path.isfile(mmi_file) or not path.isfile(mms_file):
        AddMsgAndPrint('Failed to locate the mmi or mms files for the state. Exiting...', 2, textFilePath)
        exit()

    mmi_RevDate = None
    with open(mmi_file) as mmi:
        while True:
            line = mmi.readline()
            if 'RevDate' in line:
                mmi_RevDate = line.split('=')[1].replace('\n','')
                break

    mms_RevDate = None
    with open(mms_file) as mms:
        while True:
            line = mms.readline()
            if 'RevDate' in line:
                mms_RevDate = line.split('=')[1].replace('\n','')
                break

    if mmi_RevDate is None or mms_RevDate is None:
        AddMsgAndPrint('Failed to retrieve RevDate from state mmi or mms files. Exiting...', 2, textFilePath)
        exit()

    ### Write Data to MMP File ###
    SetProgressorLabel('Writing data to project MMP file...')
    AddMsgAndPrint('\nWriting data to project MMP file...', textFilePath=textFilePath)
    env = Environment(loader=FileSystemLoader('templates'))
    template = env.get_template('template.mmp')
    output_template = template.render(mmp_version=mmp_version, run_date=run_date, run_time=run_time, mmi_RevDate=mmi_RevDate, mms_RevDate=mms_RevDate, admin_data=admin_data, gnt_fields=gnt_fields)
    
    with open(outputMMPFile, 'wb') as f:
        f.write(output_template.encode('utf-8'))
    
    ### Launch MMP ###
    try:
        startfile(outputMMPFile)
    except:
        AddMsgAndPrint('Failed to launch MMP', 2, textFilePath)


except SystemExit:
    pass

except:
    try:
        AddMsgAndPrint(errorMsg('Create MMP File'), 2, textFilePath)
    except FileNotFoundError:
        AddMsgAndPrint(errorMsg('Create MMP File'), 2)
