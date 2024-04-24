# SDA_CreateGNT_SoilMaps3.py
#
# Uses AOI in ArcMap to create a soil data table from SDA Query service. Developed as a proof-of-concept for GNT soils data.
#
# 2020-09-18 Steve Peaslee
#
# Trick: Use NotePad++ to find non-ascii characters. Search|Find Characters In Range|Non-ASCII Characters (128-255)

import sys, os, arcpy, requests, json, time, datetime, math

from arcpy import env
from arcpy.mp import ArcGISProject, LayerFile
from random import randint

from utils import AddMsgAndPrint, errorMsg

class MyError(Exception):
    pass


def elapsedTime(start):
    # Calculate amount of time since "start" and return time string
    try:
        # Stop timer
        end = time.time()

        # Calculate total elapsed seconds
        eTotal = end - start

        # day = 86400 seconds
        # hour = 3600 seconds
        # minute = 60 seconds

        eMsg = ""

        # calculate elapsed days
        eDay1 = eTotal / 86400
        eDay2 = math.modf(eDay1)
        eDay = int(eDay2[1])
        eDayR = eDay2[0]

        if eDay > 1:
          eMsg = eMsg + str(eDay) + " days "
        elif eDay == 1:
          eMsg = eMsg + str(eDay) + " day "

        # Calculated elapsed hours
        eHour1 = eDayR * 24
        eHour2 = math.modf(eHour1)
        eHour = int(eHour2[1])
        eHourR = eHour2[0]

        if eDay > 0 or eHour > 0:
            if eHour > 1:
                eMsg = eMsg + str(eHour) + " hours "
            else:
                eMsg = eMsg + str(eHour) + " hour "

        # Calculate elapsed minutes
        eMinute1 = eHourR * 60
        eMinute2 = math.modf(eMinute1)
        eMinute = int(eMinute2[1])
        eMinuteR = eMinute2[0]

        if eDay > 0 or eHour > 0 or eMinute > 0:
            if eMinute > 1:
                eMsg = eMsg + str(eMinute) + " minutes "
            else:
                eMsg = eMsg + str(eMinute) + " minute "

        # Calculate elapsed secons
        eSeconds = "%.1f" % (eMinuteR * 60)

        if eSeconds == "1.00":
            eMsg = eMsg + eSeconds + " second "
        else:
            eMsg = eMsg + eSeconds + " seconds "

        return eMsg

    except:
        errorMsg()
        return ""


def CreateAOILayer(inputAOI, aoiShp):
    # Create new featureclass to use in assembling geometry query for Soil Data Access
    # Try to create landunit identification using CLU or PLU field attributes if available.
    # What about state and county fipscodes for use in CRP? Need to add check for those 2 fields
    # and include those in the Dissolve.
    try:
        simpleShp = os.path.join(env.scratchGDB, "aoi_simple")

        if arcpy.Exists(simpleShp):
            arcpy.Delete_management(simpleShp, "FEATURECLASS")

        if arcpy.Exists(aoiShp):
            arcpy.Delete_management(aoiShp, "FEATURECLASS")

        # For CLU, sometimes a 400 error from ArcGIS Server here
        arcpy.MultipartToSinglepart_management(inputAOI, simpleShp)

        cnt = int(arcpy.GetCount_management(simpleShp).getOutput(0))

        if cnt == 0:
            raise MyError("No polygon features in " + simpleShp)

        # Try applying output coordinate system and datum transformation
        env.outputCoordinateSystem = sdaCS
        env.geographicTransformations = tm

        # Describe the single-part AOI layer
        desc = arcpy.Describe(simpleShp)
        fields = desc.fields
        fldNames = [f.baseName.upper() for f in fields]

        # Keep original boundaries, but if attribute table contains landunit or LANDUNIT attributes, dissolve on that

        if ("FSAFARM" in fldNames and "FSATRACT" in fldNames and "FSAFIELD" in fldNames):
            # This must be a shapefile export from GNT-CD
            # Go ahead and dissolve using landunit which was previously added

            if not "LANDUNIT" in fldNames:
                arcpy.AddField_management(simpleShp, "landunit", "TEXT", "", "", 16)

            curFields = ["landunit", "fsatract", "fsafarm"]

            with arcpy.da.UpdateCursor(simpleShp, curFields) as cur:
                for rec in cur:
                    # create stacked label for tract and field
                    landunit = "T" + str(rec[1]) + " F" + str(rec[2])
                    rec[0] = landunit
                    cur.updateRow(rec)

            arcpy.Dissolve_management(simpleShp, aoiShp, ["landunit"], "", "MULTI_PART")
            arcpy.Delete_management(simpleShp)

        env.workspace = env.scratchFolder

        if not arcpy.Exists(aoiShp):
            raise MyError("Missing AOI " + aoiShp)

        arcpy.RepairGeometry_management(aoiShp, "DELETE_NULL")  # Need to make sure this isn't doing bad things.

        # Calculate field acres here
        arcpy.AddField_management(aoiShp, "acres", "DOUBLE")

        # Get centroid of aoiShp which has a CS of Geographic WGS1984
        aoiDesc = arcpy.Describe(aoiShp)
        extent = aoiDesc.extent
        xCntr = (extent.XMax + extent.XMin) / 2.0
        yCntr = (extent.YMax + extent.YMin) / 2.0
        utmZone = int( (31 + (xCntr / 6.0) ) )

        # Calculate hemisphere and UTM Zone
        if yCntr > 0:  # Not sure if this is the best way to handle hemisphere
            zone = str(utmZone) + "N"
        else:
            zone = str(utmZone) + "S"

        # Central Meridian
        cm = ((utmZone * 6.0) - 183.0)

        # Get string version of UTM coordinate system
        utmBase = "PROJCS['WGS_1984_UTM_Zone_xxx',GEOGCS['GCS_WGS_1984',DATUM['D_WGS_1984',SPHEROID['WGS_1984',6378137.0,298.257223563]],PRIMEM['Greenwich',0.0],UNIT['Degree',0.0174532925199433]],PROJECTION['Transverse_Mercator'],PARAMETER['False_Easting',500000.0],PARAMETER['False_Northing',0.0],PARAMETER['Central_Meridian',zzz],PARAMETER['Scale_Factor',0.9996],PARAMETER['Latitude_Of_Origin',0.0],UNIT['Meter',1.0]];-5120900 -9998100 10000;-100000 10000;-100000 10000;0.001;0.001;0.001;IsHighPrecision"
        wkt = utmBase.replace("xxx", zone).replace("zzz", str(cm))
        utmCS = arcpy.SpatialReference()
        utmCS.loadFromString(wkt)

        acitve_map.spatialReference = utmCS

        # Temporary test to add diagnostic information
        aoiAcres = 0

        with arcpy.da.UpdateCursor(aoiShp, ["SHAPE@AREA", "acres"], "", utmCS) as cur:
            # area is in UTM coordinate system (Meters)
            for rec in cur:
                if not rec[0] is None:
                    acres = round((rec[0] / 4046.8564224), 2)  # can't handle NULL
                    aoiAcres += acres
                    newrec = [rec[0], acres]
                    cur.updateRow(newrec)
                else:
                    raise MyError("Failed to get polygon area for AOI geometry")

        if aoiAcres > 50000:
            AddMsgAndPrint(" \nWarning! Very large AOI size: " + str(aoiAcres) + " acres", 1)

        else:
            AddMsgAndPrint(" \nTotal landunit acres: " + str(aoiAcres), 0)

        return True

    except MyError as e:
        AddMsgAndPrint(str(e), 2)
        return False

    except:
        errorMsg()
        return False


def AddNewFields(newTable, columnNames, columnInfo):
    # Create the empty output table using Soil Data Access table metadata
    # ColumnNames and columnInfo come from the Attribute query JSON string
    # MUKEY would normally be included in the list, but it should already exist in the output featureclass
    try:
        # Dictionary: SQL Server to FGDB
        dType = dict()
        dType["int"] = "long"
        dType["bigint"] = "long"
        dType["smallint"] = "short"
        dType["tinyint"] = "short"
        dType["bit"] = "short"
        dType["varbinary"] = "blob"
        dType["nvarchar"] = "text"
        dType["varchar"] = "text"
        dType["char"] = "text"
        dType["datetime"] = "date"
        dType["datetime2"] = "date"
        dType["smalldatetime"] = "date"
        dType["decimal"] = "double"
        dType["numeric"] = "double"
        dType["float"] = "double"
        dType["udt"] = "text"  # probably geometry or geography data
        dType["xml"] = "text"

        dType2 = dict()
        dType2["ProviderSpecificDataType"] = "Microsoft.SqlServer.Types.SqlGeometry"

        # numeric type conversion depends upon the precision and scale
        dType["numeric"] = "float"  # 4 bytes
        dType["real"] = "double" # 8 bytes

        # Introduce option for field aliases
        # Use uppercase physical name as key
        dAliases = dict()
        dAliases["MU_KFACTOR"] = "Kw"
        dAliases["SOIL_SLP_LGTH_FCTR"] = "LS"
        dAliases["MU_TFACTOR"] = "T"
        dAliases["NA1"] = "C"
        dAliases["MU_IFACTOR"] = "WEI"
        dAliases["SOIL_LCH_IND"] = "LCH"
        dAliases["LONG_LEAF_SUIT_IND"] = "LLP"
        dAliases["WESL_IND"] = "WESL"
        dAliases["NA2"] = "Water EI"
        dAliases["MUKEY"] = "mukey"
        dAliases["NA3"] = "Wind EI"
        dAliases["NCCPI"] = "NCCPI"
        dAliases["NA4"] = "RKLS"
        dAliases["CFACTOR"] = "CFactor"
        dAliases["RFACTOR"] = "RFactor"
        dAliases["NIRRCAPCLASS"] = "NIrrCapClass"
        dAliases["POLY_ACRES"] = "PolyAcres"

        # Iterate through list of field names and add them to the output table
        i = 0
        joinFields = list()

        # Get list of existing fields iin newTable
        existingFlds = [fld.name.upper() for fld in arcpy.Describe(newTable).fields]

        for i, fldName in enumerate(columnNames):
            if fldName is None or fldName == "":
                raise MyError("Query for " + os.path.basenaame(newTable) + " returned an empty fieldname (" + str(columnNames) + ")")

            vals = columnInfo[i].split(",")
            length = int(vals[1].split("=")[1])
            precision = int(vals[2].split("=")[1])
            scale = int(vals[3].split("=")[1])
            dataType = dType[vals[4].lower().split("=")[1]]

            if fldName.upper() in dAliases:
                alias = dAliases[fldName.upper()]

            else:
                alias = fldName

            if fldName.upper() == "MUKEY":
                # switch to SSURGO standard TEXT 30 chars
                dataType = "text"
                length = 30
                precision = ""
                scale = ""

            if fldName.upper() == "MU_IFACTOR":
                # switch to integer so that map legend sorts numerically instead of alphabetically
                dataType = "short"
                length = 0
                precision = ""
                scale = ""

            if not fldName.upper() in existingFlds and not dataType == "udt" and not fldName.upper() in ["WKTGEOM", "WKBGEOG", "SOILGEOG"]:
                arcpy.AddField_management(newTable, fldName, dataType, precision, scale, length, alias)
                joinFields.append(fldName)

        if arcpy.Exists(newTable):
            return joinFields

        else:
            return []

    except MyError as e:
        AddMsgAndPrint(str(e), 2)
        return []

    except:
        errorMsg()
        return []


def IdentifyWater(soilsDetailed):
    # Using Soils_Detailed table, identify mukeys for water
    # Need to convert mukeys from integer to text EVERYWHERE
    try:
        wc = "musym = 'W' OR muname = 'Water' OR muname LIKE 'Water %' OR muname LIKE 'Water, %'"
        waterMukeys = list()

        with arcpy.da.SearchCursor(soilsDetailed, ["musym", "muname", "mukey"], where_clause=wc) as cur:
            for rec in cur:
                mukey = rec[2]
                if not mukey in waterMukeys:
                    waterMukeys.append(str(mukey))

        return waterMukeys

    except MyError as e:
        AddMsgAndPrint(str(e), 2)
        return []

    except:
        errorMsg()
        return []


def GetUniqueValues(theInput, fieldName):
    # Create bracketed list of MUKEY values from spatial layer for use in query
    try:
        # Tell user how many features are being processed
        theDesc = arcpy.Describe(theInput)
        theDataType = theDesc.dataType
        AddMsgAndPrint("", 0)

        # Get Featureclass and total count
        if theDataType.lower() == "featurelayer":
            theFC = theDesc.featureClass.catalogPath
            theResult = arcpy.GetCount_management(theFC)

        elif theDataType.lower() in ["table", "featureclass", "shapefile"]:
            theResult = arcpy.GetCount_management(theInput)

        else:
            raise MyError("Unknown data type: " + theDataType.lower())

        iTotal = int(theResult.getOutput(0))

        if iTotal > 0:
            sqlClause = ("DISTINCT " + fieldName, "ORDER BY " + fieldName)
            valList = list()
            with arcpy.da.SearchCursor(theInput, [fieldName], sql_clause=sqlClause) as cur:
                for rec in cur:
                    val = str(rec[0]).encode('ascii')
                    if not val == '' and not val in valList:
                        valList.append(val)

            return valList

        else:
            return []

    except MyError as e:
        AddMsgAndPrint(str(e), 2)
        return []

    except:
        errorMsg()
        return []


def FormSDA_Geom_Query(aoiDiss):
    # This is the spatial part of the query for GNT. Some mapunit and landunit attributes are returned
    # Other queries can be appended, but they will need to reference the temporary table names used
    # in this part of the query:
    # #AoiTable
    # #AoiAcres
    # #AoiSoils
    # #AoiSoils2
    # #AoiSoils3
    try:
        # get spatial reference from aoiDiss, need to make sure appropriate datum transformation is applied
        gcs = arcpy.SpatialReference(epsgWGS84)
        wkt = ""
        landunit = ""
        now = datetime.datetime.now()
        timeStamp = now.strftime('%Y-%m-%d T%H:%M:%S')

        # sQuery is the query string that will be incorporated into the SDA request
        header = """/** SDA Query application="CRP" rule="GNT Soil Map" version="0.1" **/"""
        sQuery =  header + "\n-- " + timeStamp
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
        with arcpy.da.SearchCursor(aoiDiss, ["landunit", "SHAPE@"]) as cur:
            for rec in cur:
                landunit = str(rec[0]).replace("\n", " ")
                polygon = rec[1]                                  # original geometry
                outputPolygon = polygon.projectAs(gcs, tm)        # simplified geometry, projected to WGS 1984
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

    except MyError:
        return ""

    except:
        errorMsg()
        return ""


def GetSDA_Attribute_Query(geomQuery, sqlPath):
    # This is the soil attribute part of the query for GNT. Some mapunit and landunit attributes are returned
    # This part of the query will need to reference the temporary table names used in the initial geometry query:
    # #AoiTable
    # #AoiAcres
    # #AoiSoils
    # #AoiSoils2
    # #AoiSoils3
    try:
        if geomQuery == "":
            raise MyError("Geometry query is empty")

        if not arcpy.Exists(sqlPath):
            raise MyError("Missing SQL file: "+ sqlPath)

        with open(sqlPath, "r") as fh:
            attQuery = fh.read()
            fh.close()

        if attQuery == "":
            raise MyError("Attribute query is an empty string")

        sQuery = geomQuery + "\n" + attQuery

        return sQuery

    except MyError:
        return ""

    except:
        errorMsg()
        return ""


def RunSDA_Queries(theURL, sQuery, gdb, utmCS):
    # Using REQUESTS library
    # POST spatial query to SDA Tabular service
    # Format JSON table containing records with MUKEY and WKT Polygons to a polygon featureclass
    try:
        AddMsgAndPrint(" \nSubmitting request to Soil Data Access...", 0)
        arcpy.SetProgressorLabel("Submitting request to Soil Data Access...")
        tableList = list() # list of new tables or featureclasses created from Soil Data Access

        # Tabular service to append to SDA URL
        url = theURL + "/" + r"Tabular/post.rest"
        dRequest = dict()
        dRequest["format"] = "JSON+COLUMNNAME+METADATA"
        dRequest["query"] = sQuery

        # Create SDM connection to service using HTTP
        sData = json.dumps(dRequest)
        timeOut = 120  # seconds which is really long. Before metrics it used to be 30 seconds.

        try:
            start = time.time()
            resp = requests.request(method="POST", url=url, data=sData, timeout=timeOut, verify=True)

            theMsg = " \nQuery response time: " + elapsedTime(start)
            AddMsgAndPrint(theMsg, 0)

        except AttributeError as err:
            theMsg = " \nSoil Data Access connection problem or AttributeError"
            AddMsgAndPrint(sQuery, 1)
            raise MyError(theMsg)

        except requests.ConnectionError as err:
            theMsg = " \nSDA connection error"
            AddMsgAndPrint(theMsg, 1)
            raise MyError(err)

        except requests.ReadTimeout as err:
            theMsg = " \nSDA timed out after: " + elapsedTime(start)
            AddMsgAndPrint(theMsg, 1)
            raise MyError(err)

        except:
            errorMsg()
            raise MyError("POST request failed for SDA query")

        status = resp.status_code

        if status == 200:
            sJSON = resp.text
            data = json.loads(sJSON)
            del resp

        else:
            del resp
            AddMsgAndPrint(sQuery, 1)
            raise MyError(str(status) + "' returned from service at " + theURL)

        if not "Table" in data:
            raise MyError("No soils data returned for this AOI request")

        else:
            # Define table names based upon sequence
            dTableNames = dict()
            dTableNames['TABLE'] = "SoilMap_by_Landunit"
            dTableNames['TABLE1'] = "MapunitAcres"
            dTableNames['TABLE2'] = "DominantSoils"

            arcpy.SetProgressorLabel("Successfully retrieved data from Soil Data Access")
            keyList = sorted(data.keys())
            arcpy.SetProgressorLabel("Importing data into ArcMap...")

            for key in keyList:
                dataList = data[key]     # Data as a list of lists. Service returns everything as string.

                # Get sequence number for table
                if key.upper() == "TABLE":
                    tableNum = 1
                else:
                    tableNum = int(key.upper().replace("TABLE", "")) + 1

                if key.upper() in dTableNames:
                    newTableName = dTableNames[key.upper()]
                else:
                    newTableName = "UnknownTable" + str(tableNum)

                # Get column names and column metadata from first two list objects
                columnList = dataList.pop(0)
                columnInfo = dataList.pop(0)
                # columnNames = [fld.encode('ascii') for fld in columnList]
                columnNames = [fld for fld in columnList]

                # SPATIAL
                if "wktgeom" in columnNames:
                    newTable = os.path.join(gdb, newTableName)
                    AddMsgAndPrint(" \nCreating new featureclass: " + newTableName , 0)
                    arcpy.SetProgressorLabel("Creating " + newTableName + " featureclass")
                    arcpy.CreateFeatureclass_management(gdb, newTableName, "POLYGON", "", "DISABLED", "DISABLED", utmCS)

                    if not arcpy.Exists(os.path.join(gdb, newTableName)):
                        raise MyError("Failed to create new featureclass: " + os.path.join(gdb, newTableName))

                    tableList.append(newTableName)

                else:
                    # no geometry present, create standalone table
                    newTable = os.path.join(gdb, newTableName)
                    arcpy.SetProgressorLabel("Creating " + newTableName + " table")
                    arcpy.CreateTable_management(gdb, newTableName)
                    tableList.append(newTableName)

                newFields = AddNewFields(newTable, columnNames, columnInfo)

                if len(newFields) == 0:
                    raise MyError("")

                # Output UTM geometry from geographic WKT
                if "wktgeom" in columnNames:
                    # include geometry column in cursor fields
                    if not utmCS is None:
                        newFields.append("SHAPE@")
                    else:
                        newFields.append("SHAPE@WKT")

                if "musym" in columnNames:
                    # Need to be able to handle uppercase field names!!!!
                    musymIndx = columnNames.index("musym")
                else:
                    musymIndx = -1

                with arcpy.da.InsertCursor(newTable, newFields) as cur:
                    if "wktgeom" in columnNames:
                        AddMsgAndPrint("\tImporting spatial data into " + newTableName, 0)
                        # This is a spatial dataset
                        geoSR = arcpy.SpatialReference(4326)

                        # output needs to be projected to UTM
                        # Note to self. If a transformation isn't needed, I should not specify one or make it an empty string.
                        # If an inappropriate method is specified, it will fail.
                        for rec in dataList:
                            # add a new polygon record
                            wkt = rec[-1]
                            gcsPoly = arcpy.FromWKT(wkt, geoSR)
                            utmPoly = gcsPoly.projectAs(utmCS, tm)
                            rec[-1] = utmPoly
                            cur.insertRow(rec)

                    else:
                        # this is a tabular-only dataset
                        # track number of records, especially for
                        AddMsgAndPrint("\tImporting tabular data into " + newTableName, 0)
                        recNum = 0

                        for rec in dataList:
                            recNum += 1
                            cur.insertRow(rec)
                            if musymIndx >= 0:
                                musym = rec[musymIndx]

                        if newTableName == "Soils_Detailed":
                            if recNum == 1 and str(musym) == "NOTCOM":
                                raise MyError("Sorry dude. The soils data for this area consists solely of NOTCOM.")

                # Create newlayer and add to ArcMap
                # This isn't being used currently. Perhaps I can use it above when the soils featureclass is created, but don't actually add it to ArcMap.
                if "wktgeom" in columnNames:
                    if newTableName != "SoilMap_by_Landunit":
                        # unless it is soils layer (save for later AddFirstSoilMap)
                        # Drop musym and muname columns from Soils_Detailed
                        # Originally I was dropping those columns in the spreadsheet function, but I'm skipping
                        # that for CRP. Move it back after spreadsheets export is working again. I don't want those columns displayed in Identify.
                        tmpFL = "TempSoilsLayer"
                        tmpLayerFile = os.path.join(env.scratchFolder, "xxSoilsLayer.lyr")
                        arcpy.MakeFeatureLayer_management(newTable, tmpFL)
                        arcpy.SaveToLayerFile_management(tmpFL, tmpLayerFile)
                        soilsLayer = LayerFile(tmpLayerFile)
                        arcpy.SetProgressorLabel("Updating soil mapunit symbology to simple outline")
                        AddMsgAndPrint(" \nUpdating soil mapunit symbology to simple outline", 1)
                        dLayerDefinition = SimpleFeaturesJSON(0.1, "black")
                        soilsLayer.updateLayerFromJSON(dLayerDefinition)
                        soilsLayer.name = newTableName
                        # mapping.AddLayer(df, soilsLayer)
                        acitve_map.addLayer(soilsLayer)
                        AddMsgAndPrint("\tCreated new soils map layer (" + soilsLayer.name + ")", 1)
                        time.sleep(1)

        return tableList

    except MyError as e:
        AddMsgAndPrint(str(e), 2)
        return []

    except:
        try:
            del resp

        except:
            pass

        errorMsg()
        return []


def AddFirstSoilMap(gdb, outputFC, thisLayerFile, labelField, thisLayerName, fieldInfo):
    # TODO: Use MakeFeatureLayer like I did in AddSoilMap. This allows for use of field_info
    # Test to see if starting with a layer file prevents the layer already exists error.
    # Create the top soil polygon layer which will be simple black outline, no fill but with MUSYM labels, visible
    # Run SDA query to add NATMUSYM and MAPUNIT NAME to featureclass
    try:
        arcpy.SetProgressorLabel("Preparing basic soil map layer...")
        newLayer = arcpy.MakeFeatureLayer_management(soilsFC, thisLayerName, "", "", fieldInfo)
        newLayer.name = thisLayerName
        arcpy.SaveToLayerFile_management(newLayer, thisLayerFile, "RELATIVE", "10.3")
        newLayer = LayerFile(thisLayerFile)

        newLayer.visible = True
        newLayer.transparency = 50
        valList = GetUniqueValues(newLayer, labelField)

        # Update soilmap layer symbology using JSON dictionary
        dLayerDefinition = UniqueValuesJSON(valList, True, "musym", True)
        newLayer.updateLayerFromJSON(dLayerDefinition)

        if arcpy.Exists("Soils_Detailed"):
            # Create relate to outputFC
            inputTbl = os.path.join(gdb, "Soils_Detailed")
            arcpy.DeleteField_management(inputTbl, "musym")
            arcpy.DeleteField_management(inputTbl, "muname")
            relclass = os.path.join(os.path.dirname(outputFC), "z" + os.path.basename(outputFC) + "_" + "Soils_Detailed")
            arcpy.CreateRelationshipClass_management(os.path.join(gdb, "Soils_Detailed"), outputFC, relclass, "SIMPLE", "< Component Data", "> Component Data", "NONE", "ONE_TO_MANY", "NONE", "mukey", "mukey")

        newLayer.transparency = 40

        return newLayer

    except MyError as e:
        AddMsgAndPrint(str(e), 2)
        return None

    except:
        errorMsg()
        return None


def AddWaterMap(detailedSoilsLayer, waterLayerName, waterMukeys):
    # Test to see if starting with a layer file prevents the layer already exists error.
    # Create the top soil polygon layer which will be simple black outline, no fill but with MUSYM labels, visible
    # Run SDA query to add NATMUSYM and MAPUNIT NAME to featureclass
    try:
        arcpy.SetProgressorLabel("Preparing water layer...")

        detailedLayerFile = os.path.join(env.scratchFolder, "xxDetailedSoils.lyr")
        detailedSoilsLayer.saveACopy(detailedLayerFile)
        waterLayer = LayerFile(detailedLayerFile)
        waterLayer.name = waterLayerName

        desc = arcpy.Describe(waterLayer)
        waterFlds = [fld.name.lower() for fld in desc.fields]

        if not "mukey" in waterFlds:
            raise MyError("Missing mukey field in water layer")

        if len(waterMukeys) > 1:
            waterDef = "mukey IN " + str(tuple(waterMukeys))

        elif len(waterMukeys) == 1:
            waterDef = "mukey = '" + str(waterMukeys[0]) + "'"

        else:
            # No water mapunits specified
            return True

        dLayerDefinition = WaterFeaturesJSON(1.0)
        waterLayer.definitionQuery = waterDef
        waterLayer.updateLayerFromJSON(dLayerDefinition)
        waterLayer.visible = True
        waterLayer.transparency = 0

        return waterLayer

    except MyError as e:
        AddMsgAndPrint(str(e), 2)
        return None

    except:
        errorMsg()
        return None


def ZoomAndRotateMap(df, utmCS):
    # Calculate dataframe angle that will point up to north and zoom to the AOI extent
    try:
        # Set the dataframe coordinate system to UTM NAD 1983
        df.spatialReference = utmCS
        extent = df.extent # XMin...

        # Get the coordinates for the center of display in UTM meters
        xCntr = ( extent.XMin + extent.XMax ) / 2.0
        yCntr = ( extent.YMin + extent.YMax ) / 2.0
        dfPoint1 = arcpy.Point(xCntr, yCntr)
        pointGeometry = arcpy.PointGeometry(dfPoint1, utmCS)

        # Create same point but as Geographic WGS1984
        # Designed to handle dataframe coordinate system datums: NAD1983 or WGS1984.
        outputSR = arcpy.SpatialReference(4326)        # GCS WGS 1984
        env.geographicTransformations = "WGS_1984_(ITRF00)_To_NAD_1983"
        pointGM = pointGeometry.projectAs(outputSR, "")
        pointGM1 = pointGM.firstPoint

        wgsX1 = pointGM1.X
        wgsY2 = pointGM1.Y + 1.0
        offsetPoint = arcpy.Point(wgsX1, wgsY2)

        # Project north offset back to dataframe coordinate system
        offsetGM = arcpy.PointGeometry(offsetPoint, outputSR)
        dfOffset = offsetGM.projectAs(utmCS, "")
        dfPoint2 = dfOffset.firstPoint
        a = [dfPoint2.X, dfPoint2.Y, 0.0]
        b = [xCntr, yCntr, 0.0]
        c = [xCntr, (yCntr + 1000.0), 0.0]

        angle = 0

        ba = [ aa-bb for aa,bb in zip(a,b) ]
        bc = [ cc-bb for cc,bb in zip(c,b) ]

        # Normalize vector
        nba = math.sqrt ( sum ( (x**2.0 for x in ba) ) )
        ba = [ x/nba for x in ba ]

        nbc = math.sqrt ( sum ( (x**2.0 for x in bc) ) )
        bc = [ x/nbc for x in bc ]

        # Calculate scalar from normalized vectors
        scale = sum ( (aa*bb for aa,bb in zip(ba,bc)) )

        # calculate the angle in radian
        radians = math.acos(scale)

        # Get the sign
        if (c[0] - a[0]) == 0:
            s = 0
        else:
            s = ( c[0] - a[0] ) / abs(c[0] - a[0])

        angle = s * ( -1.0 * round(math.degrees(radians), 1) )
        df.rotation = angle

        return True

    except MyError as e:
        AddMsgAndPrint(str(e), 2)
        return False

    except:
        errorMsg()
        return False


def AddLabels(mapLayer, labelField, fontSize, fontColor='black'):
    # Set layer label properties to use MUSYM
    # Some layers we just want to set the label properties to use MUSYM, but we don't want to display the labels.
    try:
        # Add mapunit symbol (MUSYM) labels
        desc = arcpy.Describe(mapLayer)
        fields = desc.fields
        fieldNames = [fld.name.lower() for fld in fields]

        if not labelField.lower() in fieldNames:
            AddMsgAndPrint("\t" + labelField + " not found in " + mapLayer.longName + "  " + ", ".join(fieldNames) + ")", 1)
            return False

        if mapLayer.supports("LABELCLASSES"):
            mapLayer.showClassLabels = True
            labelCls = mapLayer.labelClasses[0]

            if fontSize > 0:

                if fontColor != "black":
                    labelString = """"<FNT size = '""" + str(fontSize) + """'><CLR """ + fontColor + """ = '255'>" & [""" + labelField + '] & "</CLR></FNT>"'
                else:
                    labelString = """"<FNT size = '""" + str(fontSize) + """'>" & [""" + labelField + '] & "</FNT>"'

                labelCls.expression = labelString
                labelCls.expression = labelString

            else:
                labelCls.expression = "[" + labelField + "]"

        else:
            AddMsgAndPrint(" \n\tLayer " + mapLayer.longName + " does not support labelclasses", 1)

        return True

    except MyError as e:
        AddMsgAndPrint(str(e), 2)
        return False

    except:
        errorMsg()
        return False


def SimpleFeaturesJSON(width, color):
    # returns JSON string for soil lines and labels layer, given the width of the outline
    try:
        fill = [255,255,255,255]       # transparent polygon fill

        if color == "black":
            outlineColor = [255, 255, 255, 255]

        elif color == "yellow":
            outlineColor = [230, 230, 0, 255]

        elif color == "red":
            outlineColor = [255, 0, 0, 255]

        elif color == "white":
            outlineColor = [0, 0, 0, 255]

        else:
            # default to black
            outlineColor = [255, 255, 255, 255]

        d = dict()
        r = dict()

        r["type"] = "simple"
        s = {"type": "esriSFS", "style": "esriSFSNull", "color": fill, "outline": { "type": "esriSLS", "style": "esriSLSSolid", "color": outlineColor, "width": width }}
        r["symbol"] = s
        d["drawingInfo"]= dict()
        d["drawingInfo"]["renderer"] = r
        return d

    except MyError as e:
        AddMsgAndPrint(str(e), 2)
        return dict()

    except:
        errorMsg()
        return dict()


def WaterFeaturesJSON(width):
    # returns JSON string for soil lines and labels layer, given the width of the outline
    try:
        outLineColor = [64, 101, 235, 255]  # dark blue polygon outline
        fill = [151,219,255,125]            # cyan polygon fill

        d = dict()
        r = dict()

        r["type"] = "simple"
        s = {"type": "esriSFS", "style": "esriSFSSolid", "color": fill, "outline": { "type": "esriSLS", "style": "esriSLSSolid", "color": outLineColor, "width": width }}
        r["symbol"] = s
        d["drawingInfo"]= dict()
        d["drawingInfo"]["renderer"] = r
        return d

    except MyError as e:
        AddMsgAndPrint(str(e), 2)
        return dict()

    except:
        errorMsg()
        return dict()


def UniqueValuesJSON(legendList, drawOutlines, ratingField, bSort):
    # returns Python dictionary for unique values template. Use this for text, choice, vtext.
    # Problem: Feature layer does not display the field name in the table of contents just below
    # the layer name. Possible bug in UpdateLayerFromJSON method?
    try:
        d = dict() # initialize return value

        # Over ride outlines and turn them off since I've created a separate outline layer.
        waterColor = [64, 101, 235, 255]
        gray = [178, 178, 178, 255]
        black = [0, 0, 0, 255]

        outLineColor = black
        if drawOutlines == False:
            outLineColor = [0, 0, 0, 0]

        if bSort:
            legendList.sort()  # this was messing up my ordered legend for interps

        d = dict()
        d["drawingInfo"] = dict()
        d["drawingInfo"]["renderer"] = dict()
        d["fields"] = list()
        d["displayField"] = ratingField  # This doesn't seem to work

        d["drawingInfo"]["renderer"]["fieldDelimiter"] = ", "
        d["drawingInfo"]["renderer"]["defaultSymbol"] = None
        d["drawingInfo"]["renderer"]["defaultLabel"] = None

        d["drawingInfo"]["renderer"]["type"] = "uniqueValue"
        d["drawingInfo"]["renderer"]["field1"] = ratingField
        d["drawingInfo"]["renderer"]["field2"] = None
        d["drawingInfo"]["renderer"]["field3"] = None
        d["displayField"] = ratingField       # This doesn't seem to work

        # Add new rating field to list of layer fields
        dAtt = dict()
        dAtt["name"] = ratingField
        dAtt["alias"] = ratingField + " alias"
        dAtt["type"] = "esriFieldTypeString"
        d["fields"].append(dAtt)              # This doesn't seem to work

        # Add each legend item to the list that will go in the uniqueValueInfos item
        cnt = 0
        legendItems = list()
        uniqueValueInfos = list()

        for cnt in range(0, len(legendList)):
            rating = legendList[cnt]  # For some reason this is not just the rating value. This is a list containing [label, value, [r,g,b]]

            if rating == 'W':
                # Water symbol
                rgb = [151,219,242,255]
                legendItems = dict()
                legendItems["value"] = rating
                legendItems["description"] = ""  # This isn't really used unless I want to pull in a description of this individual rating
                legendItems["label"] = rating
                symbol = {"type" : "esriSFS", "style" : "esriSFSSolid", "color" : rgb, "outline" : {"color": waterColor, "width": 1.5, "style": "esriSLSSolid", "type": "esriSLS"}}
                legendItems["symbol"] = symbol
                uniqueValueInfos.append(legendItems)

            if rating == 'Not rated':
                # Gray shade
                rgb = gray
                legendItems = dict()
                legendItems["value"] = rating
                legendItems["description"] = ""  # This isn't really used unless I want to pull in a description of this individual rating
                legendItems["label"] = rating
                symbol = {"type" : "esriSFS", "style" : "esriSFSSolid", "color" : rgb, "outline" : {"color": outLineColor, "width": 0, "style": "esriSLSSolid", "type": "esriSLS"}}
                legendItems["symbol"] = symbol
                uniqueValueInfos.append(legendItems)

            else:
                # calculate rgb colors
                if ratingField.lower() == "musym":
                    rgb = [randint(0, 255), randint(0, 255), randint(0, 255), 255]  # for random colors

                else:
                    rgb = rating[2]

                legendItems = dict()
                legendItems["value"] = rating
                legendItems["description"] = ""  # This isn't really used unless I want to pull in a description of this individual rating
                legendItems["label"] = rating
                symbol = {"type" : "esriSFS", "style" : "esriSFSSolid", "color" : rgb, "outline" : {"color": outLineColor, "width": 0.4, "style": "esriSLSSolid", "type": "esriSLS"}}
                legendItems["symbol"] = symbol
                uniqueValueInfos.append(legendItems)

        d["drawingInfo"]["renderer"]["uniqueValueInfos"] = uniqueValueInfos

        return d

    except MyError as e:
        AddMsgAndPrint(str(e), 2)
        return d

    except:
        errorMsg()
        return d


def AddFieldMap(aoiPolys, gdb, landunitName):
    # Add AOI layer with PartName labels to ArcMap display
    try:
        tmpLandunitLayer = "tmpLandunits"

        if arcpy.Exists(aoiPolys):
            if arcpy.Exists(tmpLandunitLayer):
                arcpy.Delete_management(tmpLandunitLayer, "FEATURELAYER")

            boundaryLayerFile = os.path.join(os.path.dirname(gdb), "Landunit_Boundary.lyr")

            if arcpy.Exists(boundaryLayerFile):
                arcpy.Delete_management(boundaryLayerFile)

            arcpy.MakeFeatureLayer_management(aoiPolys, tmpLandunitLayer)
            arcpy.SaveToLayerFile_management(tmpLandunitLayer, boundaryLayerFile, "ABSOLUTE")
            arcpy.Delete_management(tmpLandunitLayer, "FEATURELAYER")

            aoiLayer = LayerFile(boundaryLayerFile)
            dLayerDefinition = SimpleFeaturesJSON(1.0, "yellow")
            aoiLayer.updateLayerFromJSON(dLayerDefinition)
            aoiLayer.name = landunitName

            arcpy.Delete_management(aoiShp, "FEATURELAYER")

            if arcpy.Exists(boundaryLayerFile):
                arcpy.Delete_management(boundaryLayerFile)

            arcpy.SaveToLayerFile_management(aoiLayer, boundaryLayerFile, "RELATIVE", "10.3")
            aoiLayer = LayerFile(boundaryLayerFile)

        else:
            raise MyError("Failed to create landunit layer (" + aoiShp + ")")

        return aoiLayer

    except MyError as e:
        AddMsgAndPrint(str(e), 2)
        return None

    except:
        errorMsg()
        return None


def GetLayerDescriptions(gdb):
    # Create a dictionary containing map layer descriptions
    try:
        dLayerDescriptions = dict()
        dLayerDescriptions['Kw'] = """Erosion factor K indicates the susceptibility of a soil to sheet and rill erosion by water. Factor K is one of six factors used in the Universal Soil Loss Equation (USLE) and the Revised Universal Soil Loss Equation (RUSLE) to predict the average annual rate of soil loss by sheet and rill erosion in tons per acre per year. The estimates are based primarily on percentage of silt, sand, and organic matter and on soil structure and saturated hydraulic conductivity (Ksat). Values of K range from 0.02 to 0.69. Other factors being equal, the higher the value, the more susceptible the soil is to sheet and rill erosion by water.

"Erosion factor Kw (whole soil)" indicates the erodibility of the whole soil. The estimates are modified by the presence of rock fragments. """

        dLayerDescriptions['T'] = """The T factor is an estimate of the maximum average annual rate of soil erosion by wind and/or water that can occur without affecting crop productivity over a sustained period. The rate is in tons per acre per year. """
        dLayerDescriptions['WEI'] = """The wind erodibility index is a numerical value indicating the susceptibility of soil to wind erosion, or the tons per acre per year that can be expected to be lost to wind erosion. There is a close correlation between wind erosion and the texture of the surface layer, the size and durability of surface clods, rock fragments, organic matter, and a calcareous reaction. Soil moisture and frozen soil layers also influence wind erosion. """
        dLayerDescriptions['NCCPI'] = """National Commodity Crop Productivity Index is a method of arraying the soils of the United States for non-irrigated commodity crop production based on their inherent soil properties. This version features a separate index for soybeans. In the past, soybeans and corn were considered together. The rating a soil is assigned is the highest one of four basic crop group indices, which are based on the climate where the crop is typically grown. Cooler climates are represented by winter wheat, moderate climates are represented by corn and soybeans, and warmer climates are represented by cotton. """
        dLayerDescriptions['LS'] = """Slope length factor represents the effect of slope length on erosion. It is the ratio of soil loss from the field slope length to that from a 72.6-foot (22.1-meter) length on the same soil type and gradient."""

        # Open LandunitMetadata table and get SSURGO saverest dates for each landunit
        mdTbl = os.path.join(gdb, "LandunitMetadata")
        soilsMetadata = "SSURGO publication dates by landunit: \n\r"

        if arcpy.Exists(mdTbl):
            with arcpy.da.SearchCursor(mdTbl, ["landunit", "soils_metadata"]) as cur:
                for rec in cur:
                    landunit, saverest = rec
                    soilsMetadata += " \n" + landunit + "\t" + saverest + "\n\r"

        dLayerDescriptions['Soils'] = soilsMetadata

        return dLayerDescriptions

    except MyError as e:
        AddMsgAndPrint(str(e), 2)
        return None

    except:
        errorMsg()
        return None


def GetUTM_CS(aoiShp):
    # Return UTM coordinate system at centroid of AOI
    try:
        # Copied from Zoom to County validation code
        newExtent = ""

        # Use GCS WGS1984 to calculate new extent and data frame rotation
        gcsSR = arcpy.SpatialReference(4326)        # GCS WGS 1984
        env.geographicTransformations = "WGS_1984_(ITRF00)_To_NAD_1983"
        acitve_map.spatialReference = gcsSR

        # This method assumes that the input county boundary featureclass is multi-part.
        # Please Note! As written this will not handle multiple polygons for the same county.
        xminList = list()
        yminList = list()
        xmaxList = list()
        ymaxList = list()

        with arcpy.da.SearchCursor(aoiShp, ["SHAPE@"], spatial_reference=gcsSR) as cur:
          for rec in cur:
            # written as a single iteration
            shape = rec[0]  # shape fails when dataframe CSR is not appropriate for new location
            newExtent = shape.extent
            xminList.append(newExtent.XMin)
            yminList.append(newExtent.YMin)
            xmaxList.append(newExtent.XMax)
            ymaxList.append(newExtent.YMax)

        xmin = min(xminList)
        ymin = min(yminList)
        xmax = max(xmaxList)
        ymax = max(ymaxList)

        if not shape is None:
          # Get extent of the AOI in decimal degrees, then expand 10%
          newExtent.XMin = xmin
          newExtent.YMin = ymin
          newExtent.XMax = xmax
          newExtent.YMax = ymax

          xOffset = (xmax - xmin) * 0.05
          yOffset = (ymax - ymin) * 0.05
          newExtent.XMin = xmin - xOffset
          newExtent.XMax = xmax + xOffset
          newExtent.YMin = ymin - yOffset
          newExtent.YMax = ymax + yOffset
          acitve_map.extent = newExtent  # newExtent based on geographic coordinate system

          # Calculate center of display in geographic
          xCntr = ( xmin + xmax ) / 2.0
          yCntr = ( ymin + ymax ) / 2.0

          # Get UTM coordinate system for new extent
          utmZone = int( (31 + (xCntr / 6.0) ) )

          # Calculate hemisphere and UTM Zone
          if yCntr > 0:  # Not sure if this is the best way to handle hemisphere
              zone = str(utmZone) + "N"

          else:
              zone = str(utmZone) + "S"

          # calculate Central Meridian for this UTM Zone
          cm = ((utmZone * 6.0) - 183.0)

          # Get coordinate reference string based upon UTM NAD 1983
          utmBase = 'PROJCS["NAD_1983_UTM_Zone_xxx",GEOGCS["GCS_North_American_1983",DATUM["D_North_American_1983",SPHEROID["GRS_1980",6378137.0,298.257222101]],PRIMEM["Greenwich",0.0],UNIT["Degree",0.0174532925199433]],PROJECTION["Transverse_Mercator"],PARAMETER["False_Easting",500000.0],PARAMETER["False_Northing",0.0],PARAMETER["Central_Meridian",-93.0],PARAMETER["Scale_Factor",0.9996],PARAMETER["Latitude_Of_Origin",0.0],UNIT["Meter",1.0]]'
          wkt = utmBase.replace("xxx", zone).replace("zzz", str(cm))
          utmPRJ = arcpy.SpatialReference()
          utmPRJ.loadFromString(wkt)

          # Set correct data frame rotation for this UTM Zone and specific location
          acitve_map.spatialReference = utmPRJ
          AddMsgAndPrint(" \nCreated new spatial reference based upon " + utmPRJ.PCSName, 1)
          return utmPRJ

    except MyError as e:
        AddMsgAndPrint(str(e), 2)
        return None

    except:
        errorMsg()
        return None


def Get_DataFrameCS(df):
    # Return data frame spatial reference if it is UTM NAD1983
    # If not return None
    try:
        sDatum = "D_NAD_1983"
        dfCS = df.spatialReference
        dfPCS = dfCS.PCSName
        dfDatum = dfCS.GCS.datumName
        # dfTransformations = df.geographicTransformations
        dfTransformations = df.transformations['2D']

        if dfPCS.startswith("NAD_1983_UTM_Zone_"):
            return dfCS

        elif dfDatum != sDatum:
            # probably WGS 1984, don't use this one
            if not sDatum in dfTransformations:
                dfTransformations.append(sDatum)

        return None

    except MyError as e:
        AddMsgAndPrint(str(e), 2)
        return None

    except:
        errorMsg()
        return None

## ===================================================================================
## MAIN
## ===================================================================================
try:
    # Read input parameters
    inputAOI = arcpy.GetParameterAsText(0)          # Input AOI feature layer
    baseFolder = arcpy.GetParameterAsText(1)        # Main folder where output tables and featureclasses may be stored
    outputName = arcpy.GetParameterAsText(2)        # Optional parameter used to name output 'CART_' folder and output geodatabase 'Soil_'

    outputLocation = os.path.join(baseFolder, outputName)

    bSpatial = True                                         # Return soil polygon geometry

    env.overwriteOutput = True

    aprx = ArcGISProject('CURRENT')
    acitve_map = aprx.activeMap
    scriptPath = os.path.dirname(sys.argv[0])
    sys.path.append(scriptPath) # set path for scripts and modules.
    sdaURL = r"https://sdmdataaccess.nrcs.usda.gov"  # manually tested this on 2019-09-13 and it worked.

    sqlPath = os.path.join(scriptPath, "GNT_Query.txt")  # attribute query

    if not arcpy.Exists(sqlPath):
        raise MyError("Missing SQL file: " + sqlPath)

    AddMsgAndPrint(" \nUsing the following Soil Data Access service: \n\t" + sdaURL, 0)

    timeOut = 0
    env.overwriteOutput = True  # See if this stops the loss of interp maps from prior runs. HydricSoilMap is the only survivor.
    env.addOutputsToMap = False

    # Check scratch geodatabase setting
    if os.path.basename(env.scratchGDB) == "Default.gdb":
        # Don't want to write to that geodatabase
        # Create a new one just for this script
        scratchGDB = os.path.join(env.scratchFolder, "scratch.gdb")

        if not arcpy.Exists(scratchGDB):
            arcpy.CreateFileGDB_management(os.path.dirname(scratchGDB), os.path.basename(scratchGDB), "10.0")
            env.scratchGDB = scratchGDB

        else:
            env.scratchGDB = scratchGDB

    # Commonly used EPSG numbers
    epsgWGS84 = 4326 # GCS WGS 1984

    # Get geographic coordinate system information for input and output layers
    validDatums = ["D_WGS_1984", "D_North_American_1983"]
    sdaCS = arcpy.SpatialReference(epsgWGS84)
    desc = arcpy.Describe(inputAOI)

    arcpy.SelectLayerByAttribute_management(inputAOI, "CLEAR_SELECTION")

    # If data frame spatial reference is not UTM NAD 1983, then None will be returned
    utmCS = Get_DataFrameCS(acitve_map)

    if utmCS is None:
        # if the data frame coordinate system is not UTM NAD1983, try using the GNTField layer
        utmCS = desc.spatialReference
        aoiName = os.path.basename(desc.nameString)

        if not utmCS.GCS.datumName in validDatums:
            raise MyError("AOI coordinate system not supported: " + utmCS.name + ", " + utmCS.GCS.datumName)

        if utmCS.GCS.datumName == "D_WGS_1984":
            tm = ""  # no datum transformation required for SDA query

        elif utmCS.GCS.datumName == "D_North_American_1983":
            tm = "WGS_1984_(ITRF00)_To_NAD_1983"

        else:
            raise MyError("AOI CS datum name: " + utmCS.GCS.datumName)

        if not utmCS.PCSName.startswith("NAD_1983_UTM_Zone"):
            # If the input layer is not UTM, get UTM spatial reference based upon the centroid of the input layer
            utmCS = GetUTM_CS(inputAOI)

        else:
            # Use the UTM coordinate system from the input GNTFields layer
            utmCS = desc.spatialReference

    else:
        # GNTField layer is UTM NAD 1983. Output soils layer will use this spatial reference
        tm = ""

    # What happens if I set the output coordinate system and transformation method to UTM here?
    # Will that create Landunit featureclass as UTM?
    AddMsgAndPrint(utmCS)
    # env.outputCoordinateSystem = utmCS
    # env.geographicTransformations = tm

    # Define temporary featureclasses for AOI, Later on move it to the gdb after it has been created
    aoiShp = os.path.join(env.scratchGDB, "myAoi")

    if arcpy.Exists(aoiShp):
        arcpy.Delete_management(aoiShp, "FEATURECLASS")

    if arcpy.Exists(aoiShp):
        raise MyError("Failed to delete previous AOI layer")

    bAOI = CreateAOILayer(inputAOI, aoiShp)  # GCS WGS 1984 to match SDA

    if bAOI == False:
        raise MyError("Problem processing landunit layer")

    aoiDesc = arcpy.Describe(aoiShp)

    # Turn off the original AOI layer so that the highlighted polygons do not clutter up the display
    # selLayers = mapping.ListLayers(mxd, inputAOI, df)

    # if len(selLayers) > 0:
    #     selLayer = selLayers[0]
    #     selLayer.visible = False
    # else:
    #     raise MyError("Selection layer not found (" + inputAOI + ")")

    # Define output geodatabase
    outputName = outputName.replace(" ", "_")
    if outputName.lower().startswith("soils"):
        gdb = os.path.join(outputLocation, outputName + ".gdb")
    else:
        gdb = os.path.join(outputLocation, "Soils_" + outputName + ".gdb")

    env.workspace = os.path.dirname(gdb)

    # Setup output layers and geodatabase
    soilLayerName = "Soil Lines and Labels for " + outputName
    landunitName = "Landunits for " + outputName
    waterLayerName = "Water for " + outputName

    # Begin by removing any map layers based upon the same geodatabase from previous runs
    # for mapLayer in [soilLayerName, landunitName, waterLayerName]:
    #     existingLayers = mapping.ListLayers(mxd, mapLayer, df)

    #     if len(existingLayers) > 0:
    #         for rmLayer in existingLayers:
    #             AddMsgAndPrint("\tRemoving existing map layer: " + rmLayer.name, 0)
    #             mapping.RemoveLayer(df, rmLayer)

    # Create output location and geodatabase
    if not arcpy.Exists(outputLocation):
        # Create new subfolder AND the new geodatabase
        arcpy.CreateFolder_management(os.path.dirname(outputLocation), os.path.basename(outputLocation))
        arcpy.CreateFileGDB_management(os.path.dirname(gdb), os.path.basename(gdb))

    else:
        # Subfolder already exists, see if the geodatabase also exists and try to overwrite it.

        if arcpy.Exists(gdb):
            # Look for tableViews from this geodatabase and remove those first
            stdTables = ["DominantSoils", "MapunitAcres"]
            ds = ""

            try:
                # for tbl in stdTables:
                #     dsTbls = arcpy.mapping.ListTableViews(mxd, tbl, df)

                #     if len(dsTbls) > 0:
                #         for ds in dsTbls:
                #             if ds.workspacePath == gdb:
                #                 arcpy.mapping.RemoveTableView(df, ds)

                #             del ds

                #     del dsTbls

                sGDB = str(gdb)

                # Now try to delete the geodatabase. Problems with file-locking here.
                env.workspace = outputLocation
                time.sleep(1.0)
                arcpy.Delete_management(gdb)
                time.sleep(0.1)
                del gdb  # attempt to remove filelock
                gdb = sGDB
                AddMsgAndPrint(" \nRemoved existing database: " + os.path.basename(gdb), 0)

            except arcpy.ExecuteError as e:
                if str(e).find("May be locked") >= 0:
                    msg = "Unable to overwrite existing geodatabase because it is locked (" + os.path.basename(sGDB) + ")"
                    raise MyError(msg)

                else:
                    raise MyError("Script execution error")

            except:
                errorMsg()
                del gdb

        arcpy.CreateFileGDB_management(os.path.dirname(gdb), os.path.basename(gdb))

    outputLocation = os.path.dirname(gdb)
    env.workspace = outputLocation

    # Copy landunit polygons to the output geodatabase
    aoiPolys = os.path.join(gdb, "Landunits")
    # env.outputCoordinateSystem = utmCS
    env.geographicTransformations = tm
    arcpy.CopyFeatures_management(aoiShp, aoiPolys)  # Why doesn't copyfeatures use outputcoordinatesystem setting?

    # bZoomed = ZoomAndRotateMap(df, utmCS)
    geomQuery = FormSDA_Geom_Query(aoiPolys)
    sQuery = GetSDA_Attribute_Query(geomQuery, sqlPath)

    if sQuery != "":
        # Send spatial query and use results to populate outputShp featureclass
        # Return list of table views that were used to create interp maps
        # Run spatial query
        tableList = RunSDA_Queries(sdaURL, sQuery, gdb, utmCS)

        if len(tableList) == 0:
            arcpy.Delete_management(gdb)
            raise MyError("Failed to get data from Soil Data Access")

        if bSpatial:
            # Try creating a temporary soils featurelayer that will be used to create the initial layer file and then immediately removed afterwards
            tmpSoils = "tmpSoilsFC"
            soilFCName = "SoilMap_by_Landunit"
            soilsLayerFile = os.path.join(env.scratchFolder, "SoilMap_Layer.lyrx")  # Base soils layer

        if bSpatial and soilFCName in tableList:
            soilsFC = os.path.join(gdb, soilFCName)

            if arcpy.Exists(tmpSoils):
                arcpy.Delete_management(tmpSoils, "FEATURELAYER")

            time.sleep(1)
            tmpSoilsLayer = arcpy.MakeFeatureLayer_management(soilsFC, tmpSoils)
            arcpy.SaveToLayerFile_management(tmpSoilsLayer, soilsLayerFile, "ABSOLUTE")
            arcpy.Delete_management(tmpSoilsLayer, "FEATURELAYER")

            if not arcpy.Exists(soilsFC):
                raise MyError("Missing soils featureclass: " + soilsFC)

            mukeyList = GetUniqueValues(soilsFC, "mukey")

            # Create field_info string that hides Shape_Area and Shape_Length in the soil map featurelayers
            desc = arcpy.Describe(soilsFC)
            fields = desc.fields
            fldInfoList = list()

            for fld in fields:
                if fld.name in ["Shape", "Shape_Area", "Shape_Length"]:
                    fldInfoList.append(fld.name + " " + fld.aliasName + " HIDDEN NONE")

                else:
                    fldInfoList.append(fld.name + " " + fld.aliasName + " VISIBLE NONE")

            fieldInfo = "; ".join(fldInfoList)
            dInterpLayers = dict()
            dLayerDescriptions = GetLayerDescriptions(gdb)

            # Soil Mapunit Map
            if arcpy.Exists(soilsFC) and arcpy.Exists(soilsLayerFile):
                # Add soil mapunit layer (with relate to component information)
                # The mapextent, map scale and dataframe rotation are set here.
                soilPolygonLayer = AddFirstSoilMap(gdb, soilsFC, soilsLayerFile, "musym", soilLayerName, fieldInfo)  # Try using soilsLayerFile to fix layer already exists error

                # Try updating the soilsLayerFile to a version that has symbology and labels.
                if arcpy.Exists(soilsLayerFile):
                    arcpy.Delete_management(soilsLayerFile)

                soilsLayerFile = os.path.join(os.path.dirname(gdb), os.path.basename(soilsLayerFile))  # switch to permanent layer location
                arcpy.SaveToLayerFile_management(soilPolygonLayer, soilsLayerFile, "RELATIVE", "10.3")
                soilPolygonLayer = LayerFile(soilsLayerFile)

                if not soilPolygonLayer is None:
                    dInterpLayers["soilslayer"] = soilPolygonLayer
                else:
                    AddMsgAndPrint(" \nUnable to add soils layer to dictionary", 1)

            # Water bodies based on musym or muname
            waterMukeys = IdentifyWater(soilPolygonLayer)

            if len(waterMukeys) > 0:
                waterTmpFile =  os.path.join(os.path.dirname(sys.argv[0]), "Water_Polygon.lyr")
                waterLayerFile =  os.path.join(os.path.dirname(gdb), "Water_Polygon.lyr")
                waterLayer = AddWaterMap(soilPolygonLayer, waterTmpFile, waterLayerName, waterMukeys)

                # Try updating the soilsLayerFile to a version that has symbology and labels.
                if arcpy.Exists(waterLayerFile):
                    arcpy.Delete_management(waterLayerFile)

                arcpy.SaveToLayerFile_management(waterLayer, waterLayerFile, "RELATIVE", "10.3")
                waterLayer = LayerFile(waterLayerFile)

            # Create aoi boundary map layer using the input aoi polygon featureclass
            if arcpy.Exists(aoiPolys):
                # new AOI layer
                arcpy.SetProgressorLabel("Preparing landunit map layer")
                landunitLayer = AddFieldMap(aoiPolys, gdb, "landunit", aprx, acitve_map, landunitName)

                if not landunitLayer is None:
                    dInterpLayers["landunitlayer"] = landunitLayer

            else:
                AddMsgAndPrint(" \nMissing " + os.path.basename(aoiPolys) + " as input for landunits", 1)

            # Add soil lines and labels layer to display
            soilLinesLayer = dInterpLayers["soilslayer"]
            layerDesc = dLayerDescriptions['Soils']
            soilLinesLayer.description = layerDesc

            if acitve_map.scale < 12000:
              soilLinesLayer.showLabels = True

            AddMsgAndPrint(" \nAdding base layer to map display: " + soilLinesLayer.name, 0)
            arcpy.SetProgressorLabel("Adding base layer to map display: " + soilLinesLayer.name)
            acitve_map.addLayer(soilLinesLayer)

            # Add water layer to group
            if len(waterMukeys) > 0:
                AddMsgAndPrint(" \nAdding water layer to map display: " + waterLayer.name, 0)
                arcpy.SetProgressorLabel("Adding water layer to map display: " + waterLayer.name)
                acitve_map.addLayer(waterLayer)

            # Add landunits layer to group
            baseLayer = dInterpLayers["landunitlayer"]

            if acitve_map.scale < 30000:
              baseLayer.showLabels = True

            AddMsgAndPrint(" \nAdding base layer to map display: " + baseLayer.name, 0)
            arcpy.SetProgressorLabel("Adding base layer to map display: " + baseLayer.name)
            acitve_map.addLayer(baseLayer)
            AddMsgAndPrint("\tSetting  extent to " + baseLayer.name, 0)
            acitve_map.extent = baseLayer.getExtent()

        elif bSpatial:
            AddMsgAndPrint(" \nEmpty spatial query, unable to retrieve soil polygons", 1)

        # if "DominantSoils" in tableList:
        #     tv = arcpy.mapping.TableView(os.path.join(gdb, "DominantSoils"))
        #     arcpy.mapping.AddTableView(df, tv)

    else:
        raise MyError("Failed to get query for Soil Data Access")

    AddMsgAndPrint(" \nUpdating display ...", 0)

    arcpy.SetProgressorLabel("Finished with CRP Soil Map Tool")


    AddMsgAndPrint(" \n ", 0)

except MyError as e:
    AddMsgAndPrint(str(e), 2)

except:
    errorMsg()
