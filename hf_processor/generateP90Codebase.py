#!/usr/bin/python
# -*- coding: UTF-8 -*-

# Copyright (C) 2014 Michel Müller, Tokyo Institute of Technology

# This file is part of Hybrid Fortran.

# Hybrid Fortran is free software: you can redistribute it and/or modify
# it under the terms of the GNU Lesser General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

# Hybrid Fortran is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU Lesser General Public License for more details.

# You should have received a copy of the GNU Lesser General Public License
# along with Hybrid Fortran. If not, see <http://www.gnu.org/licenses/>.

#**********************************************************************#
#  Procedure        generateF90fromH90AndAnalyzedCallGraph.py          #
#  Comment          Takes one h90 file and the associated complete     #
#                   callgraph and produces a compilable F90 file       #
#  Date             2012/08/01                                         #
#  Author           Michel Müller (AOKI Laboratory)                    #
#**********************************************************************#


from xml.dom.minidom import Document
from DomHelper import parseString, ImmutableDOMDocument
from optparse import OptionParser
from H90CallGraphParser import H90toF90Printer, getSymbolsByName, getModuleNodesByName, getParallelRegionData, getSymbolsByRoutineNameAndSymbolName, getSymbolsByModuleNameAndSymbolName
from GeneralHelper import openFile, getDataFromFile, setupDeferredLogging
from RecursiveDirEntries import dirEntries
from H90SymbolDependencyGraphAnalyzer import SymbolDependencyAnalyzer
from io import FileIO
import os
import errno
import sys
import json
import traceback
import StringIO
import FortranImplementation
import logging

##################### MAIN ##############################
#get all program arguments
parser = OptionParser()
parser.add_option("-i", "--sourceDir", dest="sourceDir",
									help="Source directory containing all h90 files for this implementation")
parser.add_option("-o", "--outputDir", dest="outputDir",
									help="Output directory to store all the P90 files generated by this script")
parser.add_option("-c", "--callgraph", dest="callgraph",
									help="analyzed callgraph XML file to read", metavar="XML")
parser.add_option("-d", "--debug", action="store_true", dest="debug",
									help="show debug print in standard error output")
parser.add_option("-m", "--implementation", dest="implementation",
									help="specify either a FortranImplementation classname or a JSON containing classnames by template name and a 'default' entry", metavar="IMP")
parser.add_option("--optionFlags", dest="optionFlags",
									help="can be used to switch on or off the following flags (comma separated): DO_NOT_TOUCH_GPU_CACHE_SETTINGS")
(options, args) = parser.parse_args()

setupDeferredLogging('preprocessor.log', logging.DEBUG)

optionFlags = [flag for flag in options.optionFlags.split(',') if flag not in ['', None]] if options.optionFlags != None else []
logging.info('Option Flags: %s' %(optionFlags))
if options.debug and 'DEBUG_PRINT' not in optionFlags:
	optionFlags.append('DEBUG_PRINT')

if (not options.sourceDir):
		logging.info("sourceDir option is mandatory. Use '--help' for informations on how to use this module")
		sys.exit(1)

if (not options.outputDir):
		logging.info("outputDir option is mandatory. Use '--help' for informations on how to use this module")
		sys.exit(1)

if (not options.callgraph):
		logging.info("callgraph option is mandatory. Use '--help' for informations on how to use this module")
		sys.exit(1)

if (not options.implementation):
	logging.info("implementation option is mandatory. Use '--help' for informations on how to use this module")
	sys.exit(1)

implementationNamesByTemplateName=None
try:
	implementationNamesByTemplateName=json.loads(getDataFromFile(options.implementation))
except ValueError as e:
	logging.info('Error decoding implementation json (%s): %s' \
		%(str(options.implementation), str(e))
	)
	sys.exit(1)
except Exception as e:
	logging.info('Could not interpret implementation parameter as json file to read. Trying to use it as an implementation name directly')
	implementationNamesByTemplateName={'default':options.implementation}
if options.debug:
	logging.info('Initializing H90toF90Printer with the following implementations: %s' %(json.dumps(implementationNamesByTemplateName)))
implementationsByTemplateName={
	templateName:getattr(FortranImplementation, implementationNamesByTemplateName[templateName])(optionFlags)
	for templateName in implementationNamesByTemplateName.keys()
}
cgDoc = parseString(getDataFromFile(options.callgraph), immutable=False)
try:
	os.mkdir(options.outputDir)
except OSError as e:
	if e.errno != errno.EEXIST:
		raise e
	pass
filesInDir = dirEntries(str(options.sourceDir), True, 'h90')

try:
	logging.info('Processing informations about the whole codebase')
	moduleNodesByName = getModuleNodesByName(cgDoc)
	parallelRegionData = getParallelRegionData(cgDoc)
	symbolAnalyzer = SymbolDependencyAnalyzer(cgDoc)
	#next line writes some information to cgDoc as a sideeffect. $$$ clean this up, ideally make cgDoc immutable everywhere for better performance
	symbolAnalysisByRoutineNameAndSymbolName = symbolAnalyzer.getSymbolAnalysisByRoutine()
	symbolsByModuleNameAndSymbolName = getSymbolsByModuleNameAndSymbolName(
		ImmutableDOMDocument(cgDoc),
		moduleNodesByName,
		symbolAnalysisByRoutineNameAndSymbolName=symbolAnalysisByRoutineNameAndSymbolName
	)
	symbolsByRoutineNameAndSymbolName = getSymbolsByRoutineNameAndSymbolName(
		ImmutableDOMDocument(cgDoc),
		parallelRegionData[2],
		parallelRegionData[1],
		symbolAnalysisByRoutineNameAndSymbolName=symbolAnalysisByRoutineNameAndSymbolName,
		debugPrint=options.debug
	)
except Exception as e:
	logging.info('Error when processing meta information about the codebase: %s' %(str(e)))
	if options.debug:
		logging.info(traceback.format_exc())
	sys.exit(1)

for fileInDir in filesInDir:
	outputPath = os.path.join(os.path.normpath(options.outputDir), os.path.splitext(os.path.basename(fileInDir))[0] + ".P90.temp")
	logging.info('Converting %s to %s' %(
		os.path.basename(fileInDir),
		outputPath
	))
	outputStream = FileIO(outputPath, mode="wb")
	try:
		f90printer = H90toF90Printer(
			ImmutableDOMDocument(cgDoc), #using our immutable version we can speed up ALL THE THINGS through caching
			implementationsByTemplateName,
			options.debug,
			outputStream,
			moduleNodesByName,
        	parallelRegionData,
        	symbolAnalysisByRoutineNameAndSymbolName,
        	symbolsByModuleNameAndSymbolName,
        	symbolsByRoutineNameAndSymbolName,
		)
		f90printer.processFile(fileInDir)
	except Exception as e:
		logging.info('Error when generating P90.temp from h90 file %s: %s%s\n' \
			%(str(fileInDir), str(e), traceback.format_exc())
		)
		logging.info(traceback.format_exc())
		os.unlink(outputPath)
		sys.exit(1)
	finally:
		outputStream.close()