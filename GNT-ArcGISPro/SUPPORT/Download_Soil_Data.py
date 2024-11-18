from datetime import datetime
from getpass import getuser
from json import dumps, loads
from os import path
from requests import ConnectionError, ReadTimeout, request
from time import ctime

from arcpy import Describe, env, Exists, GetParameterAsText, FromWKT, SetProgressorLabel, SpatialReference
from arcpy.analysis import SummarizeWithin
from arcpy.da import InsertCursor, SearchCursor, UpdateCursor
from arcpy.management import AddField, CreateFeatureclass, CreateTable, Dissolve
from arcpy.mp import ArcGISProject

from utils import AddMsgAndPrint, deleteLayers, errorMsg

SDA_URL = r"https://sdmdataaccess.nrcs.usda.gov"

textFilePath = ''
def logBasicSettings(textFilePath, gnt_layer):
    with open(textFilePath, 'a+') as f:
        f.write('\n######################################################################\n')
        f.write('Executing Tool: Download Soil Data\n')
        f.write(f"User Name: {getuser()}\n")
        f.write(f"Date Executed: {ctime()}\n")
        f.write('User Parameters:\n')
        f.write(f"\tGNTFieldLayer: {gnt_layer}\n")


def AddNewFields(new_table, column_names, column_info):
    '''
    Create the empty output table using Soil Data Access table metadata.
    ColumnNames and columnInfo come from the Attribute query JSON string.
    MUKEY would normally be included in the list, but should already exist in the output featureclass.
    '''
    try:
        # Dictionary: SQL Server to FGDB
        dType = dict()
        dType['int'] = 'long'
        dType['bigint'] = 'long'
        dType['smallint'] = 'short'
        dType['tinyint'] = 'short'
        dType['bit'] = 'short'
        dType['varbinary'] = 'blob'
        dType['nvarchar'] = 'text'
        dType['varchar'] = 'text'
        dType['char'] = 'text'
        dType['datetime'] = 'date'
        dType['datetime2'] = 'date'
        dType['smalldatetime'] = 'date'
        dType['decimal'] = 'double'
        dType['numeric'] = 'double'
        dType['float'] = 'double'
        dType['udt'] = 'text'  # probably geometry or geography data
        dType['xml'] = 'text'
        dType['numeric'] = 'float'  # 4 bytes
        dType['real'] = 'double' # 8 bytes

        # Option for field aliases, Use uppercase physical name as key
        dAliases = dict()
        dAliases['MU_KFACTOR'] = 'Kw'
        dAliases['SOIL_SLP_LGTH_FCTR'] = 'LS'
        dAliases['MU_TFACTOR'] = 'T'
        dAliases['NA1'] = 'C'
        dAliases['MU_IFACTOR'] = 'WEI'
        dAliases['SOIL_LCH_IND'] = 'LCH'
        dAliases['LONG_LEAF_SUIT_IND'] = 'LLP'
        dAliases['WESL_IND'] = 'WESL'
        dAliases['NA2'] = 'Water EI'
        dAliases['MUKEY'] = 'mukey'
        dAliases['NA3'] = 'Wind EI'
        dAliases['NCCPI'] = 'NCCPI'
        dAliases['NA4'] = 'RKLS'
        dAliases['CFACTOR'] = 'CFactor'
        dAliases['RFACTOR'] = 'RFactor'
        dAliases['NIRRCAPCLASS'] = 'NIrrCapClass'
        dAliases['POLY_ACRES'] = 'PolyAcres'

        # Iterate through list of field names and add them to the output table
        i = 0
        joinFields = list()
        existingFlds = [fld.name.upper() for fld in Describe(new_table).fields]

        for i, fldName in enumerate(column_names):
            if fldName is None or fldName == '':
                AddMsgAndPrint(f"Query for {path.basenaame(new_table)} returned an empty fieldname ({str(column_names)})", 2)
                exit()

            vals = column_info[i].split(',')
            length = int(vals[1].split('=')[1])
            precision = int(vals[2].split('=')[1])
            scale = int(vals[3].split('=')[1])
            dataType = dType[vals[4].lower().split('=')[1]]

            if fldName.upper() in dAliases:
                alias = dAliases[fldName.upper()]

            else:
                alias = fldName

            if fldName.upper() == 'MUKEY':
                # switch to SSURGO standard TEXT 30 chars
                dataType = 'text'
                length = 30
                precision = ''
                scale = ''

            if fldName.upper() == 'MU_IFACTOR':
                # switch to integer so that map legend sorts numerically instead of alphabetically
                dataType = 'short'
                length = 0
                precision = ''
                scale = ''

            if not fldName.upper() in existingFlds and not dataType == 'udt' and not fldName.upper() in ['WKTGEOM', 'WKBGEOG', 'SOILGEOG']:
                AddField(new_table, fldName, dataType, precision, scale, length, alias)
                joinFields.append(fldName)

        if Exists(new_table):
            return joinFields
        else:
            return []

    except:
        errorMsg('Download Soil Data')
        return []


def FormSDA_Geom_Query(aoi):
    '''
    This is the spatial part of the query for GNT. Some mapunit and landunit attributes are returned
    Other queries can be appended, but they will need to reference the temporary table names used:
    AoiTable, AoiAcres, AoiSoils, AoiSoils2, AoiSoils3
    '''
    try:
        # get spatial reference from aoiDiss, need to make sure appropriate datum transformation is applied
        gcs = SpatialReference(4326)
        wkt = ''
        landunit = ''
        now = datetime.now().strftime('%Y-%m-%d T%H:%M:%S')

        # sQuery is the query string that will be incorporated into the SDA request
        header = """/** SDA Query application="CRP" rule="GNT Soil Map" version="0.1" **/"""
        sQuery =  header + "\n-- " + now
        sQuery += """\n-- Declare all variables here
~DeclareVarchar(@dateStamp,20)~
~DeclareGeometry(@aoiGeom)~
~DeclareGeometry(@aoiGeomFixed)~

-- Create AOI table with polygon geometry. Coordinate system must be WGS1984 (EPSG 4326)
CREATE TABLE #AoiTable
    ( aoiid INT IDENTITY (1,1),
    landunit VARCHAR(20),
    aoigeom GEOMETRY )
;

-- Insert identifier string and WKT geometry for each AOI polygon after this...
"""

        # Project geometry from AOI
        with SearchCursor(aoi, ['landunit', 'SHAPE@']) as cur:
            for rec in cur:
                landunit = str(rec[0]).replace('\n', ' ')
                polygon = rec[1]                                  # original geometry
                outputPolygon = polygon.projectAs(gcs, '')        # simplified geometry, projected to WGS 1984
                wkt = outputPolygon.WKT
                sQuery += " \nINSERT INTO #AoiTable ( landunit, aoigeom ) "
                sQuery += " \nVALUES ('" + landunit + "', geometry::STGeomFromText('" + wkt + "', 4326));"

        sQuery += """

-- End of AOI geometry section

-- #AoiAcres table to contain summary acres for each landunit
CREATE TABLE #AoiAcres
    ( aoiid INT,
    landunit VARCHAR(20),
    landunit_acres FLOAT )
;

-- #AoiSoils table contains intersected soil polygon table with geometry
CREATE TABLE #AoiSoils
    ( polyid INT IDENTITY (1,1),
    aoiid INT,
    landunit VARCHAR(20),
    musym VARCHAR(6),
    mukey INT,
    soilgeom GEOMETRY )
;

-- #AoiSoils2 table contains Soil geometry with landunits
CREATE TABLE #AoiSoils2
    ( aoiid INT,
    landunit VARCHAR(20),
    musym VARCHAR(6),
    mukey INT,
    soilgeom GEOMETRY )
;

-- #AoiSoils3 table contains Soil geometry with landunits
CREATE TABLE #AoiSoils3
    ( aoiid INT,
    landunit VARCHAR(20),
    musym VARCHAR(6),
    mukey INT,
    poly_acres FLOAT,
    soilgeog GEOGRAPHY )
;

--  #LuMuAcres table contains Soil map unit acres, aggregated by mukey (merges polygons together)
CREATE TABLE  #LuMuAcres
    ( aoiid INT,
    landunit VARCHAR(20),
    musym VARCHAR(6),
    mukey INT,
    mapunit_acres FLOAT )
;

"""
        # Return Soil Data Access query string
        return sQuery

    except:
        errorMsg('Download Soil Data')
        return ''


def RunSDA_Queries(sda_url, sQuery, gdb, fd, utmCS, textFilePath):
    '''
    POST spatial query to SDA Tabular service using requests library.
    Format JSON table containing records with MUKEY and WKT Polygons to a polygon featureclass.
    '''
    try:
        AddMsgAndPrint('\nSubmitting request to Soil Data Access...', textFilePath=textFilePath)
        SetProgressorLabel('Submitting request to Soil Data Access...')
        tableList = list() # list of new tables or featureclasses created from Soil Data Access

        # Tabular service to append to SDA URL
        url = f"{sda_url}/Tabular/post.rest"
        dRequest = dict()
        dRequest['format'] = 'JSON+COLUMNNAME+METADATA'
        dRequest['query'] = sQuery

        # Create SDM connection to service using HTTP
        sData = dumps(dRequest)
        timeOut = 120  # seconds which is really long. Before metrics it used to be 30 seconds.

        try:
            resp = request(method='POST', url=url, data=sData, timeout=timeOut, verify=True)

        except AttributeError:
            AddMsgAndPrint('\nSDA AttributeError', 2)
        except ConnectionError:
            AddMsgAndPrint('\nSDA ConnectionError', 2)
        except ReadTimeout:
            AddMsgAndPrint('\nSDA REadTimeout', 2)
        except:
            errorMsg('Download Soil Data')

        status = resp.status_code

        if status == 200:
            sJSON = resp.text
            data = loads(sJSON)
        else:
            AddMsgAndPrint(f"\nSDA query request returned status: {status}", 2, textFilePath)
            exit()

        if 'Table' not in data:
            AddMsgAndPrint('\nNo soils data returned for this AOI request', 2, textFilePath)
            exit()
        else:
            SetProgressorLabel('Successfully retrieved data from Soil Data Access')
            AddMsgAndPrint('\nSuccessfully retrieved data from Soil Data Access...', textFilePath=textFilePath)
            
            # Define table names based upon sequence
            dTableNames = dict()
            dTableNames['TABLE'] = 'SoilMap_by_Landunit'
            dTableNames['TABLE1'] = 'MapunitAcres'
            dTableNames['TABLE2'] = 'DominantSoils'

            keyList = sorted(data.keys())
            for key in keyList:
                dataList = data[key] # Data as a list of lists. Service returns everything as string.

                # Get sequence number for table
                if key.upper() == 'TABLE':
                    tableNum = 1
                else:
                    tableNum = int(key.upper().replace('TABLE', '')) + 1

                if key.upper() in dTableNames:
                    newTableName = dTableNames[key.upper()]
                else:
                    newTableName = f"UnknownTable{str(tableNum)}"

                # Get column names and column metadata from first two list objects
                columnList = dataList.pop(0)
                columnInfo = dataList.pop(0)
                # Hack to increase field length of 'musym' in output feature class
                columnInfo[3] = columnInfo[3].replace('ColumnSize=6', 'ColumnSize=12')
                # columnNames = [fld.encode('ascii') for fld in columnList] NOTE: This throws error from Pro
                columnNames = [fld for fld in columnList]

                if 'wktgeom' in columnNames:
                    # geometry present, create feature class
                    newTable = path.join(fd, newTableName)
                    AddMsgAndPrint(f"\nCreating new featureclass: {newTableName}", textFilePath=textFilePath)
                    SetProgressorLabel(f"Creating new featureclass: {newTableName}")
                    CreateFeatureclass(fd, newTableName, 'POLYGON', '', 'DISABLED', 'DISABLED', utmCS)

                    if not Exists(path.join(fd, newTableName)):
                        AddMsgAndPrint(f"Failed to create new featureclass: {path.join(fd, newTableName)}", 2, textFilePath)

                    tableList.append(newTableName)

                else:
                    # no geometry present, create standalone table
                    newTable = path.join(gdb, newTableName)
                    AddMsgAndPrint(f"\nCreating new table: {newTableName}", textFilePath=textFilePath)
                    SetProgressorLabel(f"Creating new table: {newTableName}")
                    CreateTable(gdb, newTableName)
                    tableList.append(newTableName)
                # AddMsgAndPrint(columnNames)
                # AddMsgAndPrint(columnInfo)
                newFields = AddNewFields(newTable, columnNames, columnInfo)

                # Output UTM geometry from geographic WKT
                if 'wktgeom' in columnNames:
                    # include geometry column in cursor fields
                    if not utmCS is None:
                        newFields.append('SHAPE@')
                    else:
                        newFields.append('SHAPE@WKT')

                if 'musym' in columnNames:
                    # Need to be able to handle uppercase field names!!!!
                    musymIndx = columnNames.index('musym')
                else:
                    musymIndx = -1

                with InsertCursor(newTable, newFields) as cur:
                    if 'wktgeom' in columnNames:
                        AddMsgAndPrint(f"\tImporting spatial data into {newTableName}", textFilePath=textFilePath)
                        # This is a spatial dataset
                        geoSR = SpatialReference(4326)

                        # output needs to be projected to UTM
                        # Note to self. If a transformation isn't needed, I should not specify one or make it an empty string.
                        # If an inappropriate method is specified, it will fail.
                        for rec in dataList:
                            # add a new polygon record
                            wkt = rec[-1]
                            gcsPoly = FromWKT(wkt, geoSR)
                            utmPoly = gcsPoly.projectAs(utmCS, '')
                            rec[-1] = utmPoly
                            cur.insertRow(rec)

                    else:
                        # Tabular-only dataset, track number of records
                        AddMsgAndPrint(f"\tImporting tabular data into {newTableName}", textFilePath=textFilePath)
                        recNum = 0

                        for rec in dataList:
                            recNum += 1
                            cur.insertRow(rec)
                            if musymIndx >= 0:
                                musym = rec[musymIndx]

                        if newTableName == 'Soils_Detailed':
                            if recNum == 1 and str(musym) == 'NOTCOM':
                                AddMsgAndPrint('\nThe soils data for this area consists solely of NOTCOM.', 2, textFilePath)
                                exit()

        return tableList

    except:
        errorMsg('Download Soil Data')
        return []

##################################################################################################################################

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


### ESRI Environment Settings ###
output_coordinate_system = Describe(gnt_layer).spatialReference
env.outputCoordinateSystem = output_coordinate_system
env.overwriteOutput = True


### Define Local Variables ###
base_dir = path.abspath(path.dirname(__file__)) #\SUPPORT
gntdataGDB_name = path.basename(gntdataGDB_path)
gntdataFD_name = 'Layers'
gntdataFD = path.join(gntdataGDB_path, gntdataFD_name)
admin_table_path = path.join(gntdataGDB_path, 'Admin_Table')
landunits_path = path.join(gntdataFD, 'Landunits')
soilunits_path = path.join(gntdataFD, 'SoilMap_by_Landunit')
soilunits_summarize_path = path.join(gntdataFD, 'Soil_Summarize')

summary_table = path.join(gntdataGDB_path, 'Summary_Table')
userWorkspace = path.dirname(gntdataGDB_path)
projectName = path.basename(userWorkspace).replace(' ', '_')
textFilePath = path.join(userWorkspace, f"{projectName}_log.txt")

sql_path = path.join(base_dir, 'GNT_Query.txt')
if not Exists(sql_path):
    AddMsgAndPrint('Missing SQL file in SUPPORT folder. Exiting...', 2)
    exit()


try:
    logBasicSettings(textFilePath, gnt_layer)

    ### Create AOI from GNTFieldLayer ###
    SetProgressorLabel('Creating area of interest layer...')
    AddMsgAndPrint('\nCreating area of interest layer...', textFilePath=textFilePath)
    Dissolve(gnt_layer, landunits_path)
    AddField(landunits_path, 'landunit', 'TEXT', '', '', 16)
    with SearchCursor(gnt_layer, ['fsatract', 'fsafarm']) as cur:
        row = cur.next()
        landunit_value = f"T{str(row[0])} F{str(row[1])}"
    with UpdateCursor(landunits_path, ['landunit']) as cur:
        for row in cur:
            row[0] = landunit_value
            cur.updateRow(row)


    ### Build Soil Data Access Query and Run ###
    SetProgressorLabel('Building geometry query...')
    AddMsgAndPrint('\nBuilding geometry query...', textFilePath=textFilePath)
    geomQuery = FormSDA_Geom_Query(landunits_path)
    if geomQuery == '':
        AddMsgAndPrint('\nEmpty geometry query. Exiting...', 2, textFilePath)
        exit()

    with open(sql_path, 'r') as f:
        attQuery = f.read()

    sQuery = f"{geomQuery}\n{attQuery}"
    # AddMsgAndPrint(f"\nQuery: {sQuery}", textFilePath=textFilePath)

    SetProgressorLabel('Reaching out to SDA...')
    tableList = RunSDA_Queries(SDA_URL, sQuery, gntdataGDB_path, gntdataFD, output_coordinate_system, textFilePath)
    AddMsgAndPrint(f"\nCreated: {tableList}", textFilePath=textFilePath)

    with UpdateCursor(soilunits_path, ['areasymbol', 'musym']) as cur:
        for row in cur:
            prefix = str(int(row[0][2:]))
            row[1] = f"{prefix}_{row[1]}"
            cur.updateRow(row)

    ### Determine Predominant Soil Type by Field ###
    SetProgressorLabel('Determining predominant soil types...')
    AddMsgAndPrint('\nDetermining predominant soil types...', textFilePath=textFilePath)
    SummarizeWithin(gnt_layer, soilunits_path, soilunits_summarize_path, 'KEEP_ALL', '', 'ADD_SHAPE_SUM', 'ACRES', 'musym', 'ADD_MIN_MAJ', '', summary_table)

    # Transfer predominant soil type to GNTField Layer
    soil_types = {}
    with SearchCursor(soilunits_summarize_path, ['SubID', 'Majority_musym']) as cur:
        for row in cur:
            soil_types[row[0]] = row[1]

    with UpdateCursor(gnt_layer, ['SubID', 'SoilKey']) as cur:
        for row in cur:
            row[1] = soil_types[row[0]]
            cur.updateRow(row)

    # Add soil layer to map
    SetProgressorLabel('Adding soil layer to map...')
    AddMsgAndPrint('\nAdding soil layer to map...', textFilePath=textFilePath)
    map.addDataFromPath(soilunits_path)
    for lyr in map.listLayers():
        if lyr.longName == 'SoilMap_by_Landunit':
            lyr.visible = False


except SystemExit:
    pass

except:
    try:
        AddMsgAndPrint(errorMsg('Download Soil Data'), 2, textFilePath)
    except FileNotFoundError:
        AddMsgAndPrint(errorMsg('Download Soil Data'), 2)

finally:
    SetProgressorLabel('Cleaning up scratch layers...')
    AddMsgAndPrint('\nCleaning up scratch layers...', textFilePath=textFilePath)
    deleteLayers([soilunits_summarize_path, summary_table, landunits_path])
    # Close and Reopen Map - BUG: Pro says setback layers are not editable
    aprx.closeViews()
    map.openView()
