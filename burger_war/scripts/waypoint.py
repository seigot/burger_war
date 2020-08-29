#!/usr/bin/env python
# -*- coding: utf-8 -*-

import csv
import math
import numpy as np

class Waypoints:

    def __init__(self, path):
        self.points = []
        self.number = 0
        self.Waypoints_Lap = 0
        self.next_target_idx = -1
        self.all_field_score = np.ones([18]) # field score state
        self._load_waypoints(path)
        print ('number of waypoints: '+str(len(self.points)))

    def _load_waypoints(self, path):
        with open(path) as f:
            lines = csv.reader(f)
            for l in lines:
                point = [float(n) for n in l]
                point[2] = point[2]*math.pi/180.0
                point[3] = int(point[3])
                self.points.append(point)

    def get_next_waypoint(self):
        self.number = self.number+1
        if self.number == len(self.points):
            self.Waypoints_Lap = self.Waypoints_Lap+1
            self.number = 0          

        # check if already get next target
        self.next_target_idx = self.points[self.number][3]
        if self.all_field_score[self.next_target_idx] == 0:
            print("already get next_target")
        
        return self.points[self.number][0:3]

    def get_current_waypoint(self):
        return self.points[self.number]

    def get_any_waypoint(self, n):
        return self.points[n]

    def set_number(self, n):
        self.number = n

    def set_field_score(self, n):
        self.all_field_score = n
        #print(self.all_field_score)
        
                


if __name__ == "__main__":
    Waypoints('waypoints.csv')
