# -*- coding: utf-8 -*-
"""
general.py: common functions for system definitions
"""
import pvlib
import pandas as pd
import datetime as DT

class Weather_Data:
    def __init__(self, files):
        self.files=files
        files.sort()

        met = pd.DataFrame()
        meta = pd.DataFrame()
        for file in files:
            temp_psm, temp_meta = pvlib.iotools.read_psm3(file,map_variables=True)
            met = pd.concat([met,temp_psm],axis=0)
            meta = pd.concat([meta,pd.DataFrame(temp_meta,index=[file])],axis=0)

        self.dataframe = met
        self.metadata = meta

class Site:
    def __init__(self, name, weather_data, time_zone, latitude=None, longitude=None, altitude=None, POI_limit = None):
        POI_limit = None
        self.name = name
        self.weather_data = weather_data
        self.time_zone = time_zone
        self.POI_limit=POI_limit

        if latitude is not None and longitude is not None and altitude is not None:
            self.latitude = latitude
            self.longitude = longitude
            self.altitude = altitude
        elif isinstance(weather_data.metadata, dict) and 'location' in weather_data.metadata:
            self.latitude = weather_data.metadata['location'].get('latitude', 0.0)
            self.longitude = weather_data.metadata['location'].get('longitude', 0.0)
            self.altitude = weather_data.metadata['location'].get('elevation', 0.0)
        else:
            self.latitude = 0.0
            self.longitude = 0.0
            self.altitude = 0.0

        self.location = pvlib.location.Location(latitude=self.latitude,
                                                longitude=self.longitude,
                                                altitude=self.altitude,
                                                tz=self.time_zone)

# class Site:
#     def __init__(self, name, weather_data, time_zone, latitude = None, longitude = None, altitude = None, POI_limit = None):
#         #from definition
#         self.name=name
#         self.weather_data=weather_data
#         self.time_zone=time_zone
#         self.POI_limit=POI_limit

#         if ((latitude != None) & (longitude != None) & (altitude != None)):
#             self.latitude=latitude
#             self.longitude=longitude
#             self.altitude=altitude
#         elif isinstance(weather_data.metadata, pd.DataFrame):
#             self.latitude=weather_data.metadata.latitude.iloc[0]
#             self.longitude=weather_data.metadata.longitude.iloc[0]
#             self.altitude=weather_data.metadata.altitude.iloc[0]
        
#         #calculated
#         self.location = pvlib.location.Location(latitude=self.latitude,
#                                            longitude=self.longitude,
#                                             altitude=self.altitude,
#                                            tz=self.time_zone)

class Load_Data:
    def __init__(self, csv='/projects/wg-ASGARD/load_data/hourly_load_23-33.csv', years = 'all'):
        self.csv = csv
        self.years = years
        
        df = pd.read_csv(self.csv,index_col=0)
        df.index = pd.DatetimeIndex(df.index)
        if self.years != 'all':
            if not isinstance(self.years,list):
                self.years = [self.years]
            df = pd.concat([df[df.index.year==year] for year in self.years],axis=0)
            
        self.load_MW = df