#!/usr/bin/env python
# -*- coding: utf-8 -*-
import rospy
import random

from std_msgs.msg import String
from geometry_msgs.msg import Twist
from sensor_msgs.msg import LaserScan
from sensor_msgs.msg import Image
from sensor_msgs.msg import JointState
from cv_bridge import CvBridge, CvBridgeError
import time
import cv2
import enemyTable as eT
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.patches as patches

# camera image 640*480
img_w = 640
img_h = 480

fieldWidth = 170
fieldHeight = 170
centerBoxWidth = 35
centerBoxHeight = 35
otherBoxWidth = 20
otherBoxHeight = 15
otherBoxDistance = 53

FIND_ENEMY_SEARCH = 0
FIND_ENEMY_FOUND = 1
FIND_ENEMY_WAIT = 2
FIND_ENEMY_LOOKON = 3

class SeigoBot():
    myPosX = 0
    myPosY = -150
    myDirect = np.pi / 2

    lidarFig = plt.figure(figsize=(5,5))
    mapFig = plt.figure(figsize=(5,5))

    def __init__(self, bot_name):
        # bot name 
        self.name = bot_name
        # velocity publisher
        self.vel_pub = rospy.Publisher('cmd_vel', Twist,queue_size=1)

        # Lidar
        self.scan = LaserScan()
        self.lidar_sub = rospy.Subscriber('/red_bot/scan', LaserScan, self.lidarCallback)
        self.front_distance = 10000 # init
        self.front_scan = 1000

        # usb camera
        self.img = None
        self.camera_preview = True
        self.bridge = CvBridge()
        self.image_sub = rospy.Subscriber('/red_bot/image_raw', Image, self.imageCallback)
        self.red_angle = -1 # init
        self.blue_angle = -1 # init
        self.green_angle = -1 # init

        self.find_enemy = FIND_ENEMY_SEARCH
        self.find_wait = 0
        self.enemy_direct = 1

        # joint
        self.joint = JointState()
        self.joint_sub = rospy.Subscriber('joint_states', JointState, self.jointstateCallback)
        self.wheel_rot_r = 0
        self.wheel_rot_l = 0
        self.moving = False

        # twist
        self.x = 0;
        self.th = 0;

    def jointstateCallback(self, data):
        # Is moving?
        if np.abs(self.wheel_rot_r - data.position[0]) < 0.01 and np.abs(self.wheel_rot_l - data.position[1]) < 0.01:
            if self.moving is True:
                print "Stop!"
            self.moving = False
        else:
            if self.moving is False:
                print "Move!"
            self.moving = True

        self.wheel_rot_r = data.position[0]
        self.wheel_rot_l = data.position[1]

    # lidar scan topic call back sample
    # update lidar scan state
    def lidarCallback(self, data):
        self.scan = data

        # visualize scan data with radar chart
        angles = np.linspace(0, 2 * np.pi, len(self.scan.ranges) + 1, endpoint=True)
        values = np.concatenate((self.scan.ranges, [self.scan.ranges[0]]))
        ax = self.lidarFig.add_subplot(111, polar=True)
        ax.cla()
        ax.plot(angles, values, 'o-')
        ax.fill(angles, values, alpha=0.25)
        ax.set_rlim(0, 3.5)

        # print(self.scan)
        # print(self.scan.ranges[0])
        # self.front_distance = self.scan.ranges[0]
        self.front_distance = min(min(self.scan.ranges[0:10]),min(self.scan.ranges[350:359]))
        self.front_scan = (sum(self.scan.ranges[0:4])+sum(self.scan.ranges[355:359])) / 10

    def find_rect_of_target_color(self, image, color_type): # r:0, g:1, b:2
        hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV_FULL)
        h = hsv[:, :, 0]
        s = hsv[:, :, 1]

        # red detection
        if color_type == 0:
            mask = np.zeros(h.shape, dtype=np.uint8)
            mask[((h < 20) | (h > 200)) & (s > 128)] = 255

        # blue detection
        if color_type == 2:
            lower_blue = np.array([130, 50, 50])
            upper_blue = np.array([200, 255, 255])
            mask = cv2.inRange(hsv, lower_blue, upper_blue)

        # green detection
        if color_type == 1:
            lower_green = np.array([75, 50, 50])
            upper_green = np.array([110, 255, 255])
            mask = cv2.inRange(hsv, lower_green, upper_green)

        # get contours
        img, contours, _ = cv2.findContours(mask, cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)
        #contours = cv2.findContours(mask, cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)
        rects = []
        for contour in contours:
            approx = cv2.convexHull(contour)
            rect = cv2.boundingRect(approx)
            rects.append(np.array(rect))
        return rects
        
    # camera image call back sample
    # comvert image topic to opencv object and show
    def imageCallback(self, data):
        redFound = False
        greenFound = False
        try:
            self.img = self.bridge.imgmsg_to_cv2(data, "bgr8")
        except CvBridgeError as e:
            print(e)

        # print(self.img);
        frame = self.img
        # red
        rects = self.find_rect_of_target_color(frame, 0)
        if len(rects) > 0:
            rect = max(rects, key=(lambda x: x[2] * x[3]))
            cv2.rectangle(frame, tuple(rect[0:2]), tuple(rect[0:2] + rect[2:4]), (0, 0, 255), thickness=2)
            # angle(rad)
            tmp_angle = ((rect[0:2]+rect[0:2]+rect[2:4])/2-(img_w/2)) *0.077
            self.red_angle = tmp_angle * np.pi / 180
            # print ( tmp_angle )
            redFound = True
            self.trackEnemy(rect)

        # green
        rects = self.find_rect_of_target_color(frame, 1)
        if len(rects) > 0:
            rect = max(rects, key=(lambda x: x[2] * x[3]))
            cv2.rectangle(frame, tuple(rect[0:2]), tuple(rect[0:2] + rect[2:4]), (0, 0, 255), thickness=2)
            # angle(rad)
            tmp_angle = ((rect[0:2]+rect[0:2]+rect[2:4])/2-(img_w/2)) *0.077
            self.green_angle = tmp_angle * np.pi / 180
            # print ( tmp_angle )
            if  redFound is False:
                greenFound = True
                self.trackEnemy(rect)

        if redFound is False and greenFound is False:
            self.trackEnemy(None)

        # blue
        rects = self.find_rect_of_target_color(frame, 2)
        if len(rects) > 0:
            rect = max(rects, key=(lambda x: x[2] * x[3]))
            cv2.rectangle(frame, tuple(rect[0:2]), tuple(rect[0:2] + rect[2:4]), (0, 0, 255), thickness=2)
            # angle(rad)
            tmp_angle = ((rect[0:2]+rect[0:2]+rect[2:4])/2-(img_w/2)) *0.077
            self.blue_angle = tmp_angle * np.pi / 180
            # print ( tmp_angle )
            
        #    if self.camera_preview:
        # print("image show")
        cv2.imshow("Image window", frame)
        cv2.waitKey(1)

    def trackEnemy(self, rect):
        # Found enemy
        if rect is not None:
            # Estimate the distance from enemy.
            if rect[1] < len(eT.enemyTable):
                d = eT.enemyTable[rect[1]] if eT.enemyTable[rect[1]] > 0 else 1
            else:
                d = 1
            # Estimate acceleration parameter
            d = d / (np.abs(rect[0] + rect[2] / 2.0 - img_w / 2.0) / float(img_w) * 4)
            # Decide the direction and the radian.
            if (rect[0] + rect[2] / 2.0) > img_w / 2.0:
                self.enemy_direct = -1 * d
            else:
                self.enemy_direct = 1 * d
            # Change state
            if self.find_enemy == FIND_ENEMY_SEARCH:
                # SEARCH->FOUND (Quick move)
                self.find_enemy = FIND_ENEMY_FOUND
                self.th = np.pi / 2.0 / self.enemy_direct
            else:
                # Maybe FOUND->LOOKON (Slow move)
                self.find_enemy = FIND_ENEMY_LOOKON
                self.th = np.pi / 16.0 / self.enemy_direct
            print("Found enemy")

        else:
            # Lost enemy...
            # State change
            # LOOKON -> WAIT
            if self.find_enemy == FIND_ENEMY_LOOKON:
                self.find_wait = time.time()
                self.find_enemy = FIND_ENEMY_WAIT
                print("Wait for re-found")
            # WAIT -> SEARCH
            elif self.find_enemy == FIND_ENEMY_WAIT:
                if time.time() - self.find_wait > 10:
                    self.find_enemy = FIND_ENEMY_SEARCH
                    print("Start Search...")

            if self.find_enemy == FIND_ENEMY_SEARCH:
                # Search enemy
                # Default radian (PI/2)
                left_scan = np.pi / 2.0
                right_scan = np.pi / 2.0 * -1
                self.enemy_direct = self.enemy_direct / np.abs(self.enemy_direct)
                if self.scan.ranges is None or self.moving is True:
                    # Now moving, do nothing!
                    print("Skip")
                    self.th = 0
                else:
                    # Is there something ahead?
                    if np.max(self.scan.ranges[0:5]) < 1.0 and np.max(self.scan.ranges[355:359]) < 1.0:
                        # Check both side, I do not watch the wall!
                        print("Blind")
                        if self.enemy_direct > 0 and np.max(self.scan.ranges[80:100]) < 1.0:
                            self.enemy_direct = self.enemy_direct * -1
                        if self.enemy_direct < 0 and np.max(self.scan.ranges[260:280]) < 1.0:
                            self.enemy_direct = self.enemy_direct * -1
                    else:
                        # Calc radian
                        for i in range(5, 90, 1):
                            if np.max(self.scan.ranges[i - 5:i + 5]) < 0.7:
                                self.enemy_direct = self.enemy_direct * -1
                                break
                        left_scan = np.pi * i / 180.0
                        for i in range(354, 270, -1):
                            if np.max(self.scan.ranges[i - 5:i + 5]) < 0.7:
                                self.enemy_direct = self.enemy_direct * -1
                                break
                        right_scan = np.pi * (i - 360) / 180.0
                    # Set radian for twist
                    if self.enemy_direct < 0:
                        self.th = right_scan
                    else:
                        self.th = left_scan
            print("Lost enemy")

    def calcTwist(self):
        x = 0
        th = self.th
        twist = Twist()
        twist.linear.x = x; twist.linear.y = 0; twist.linear.z = 0
        twist.angular.x = 0; twist.angular.y = 0; twist.angular.z = th

        self.vel_pub.publish(twist)
        self.drawMap()

        return twist

    def drawMap(self):
        myPosX = self.myPosX
        myPosY = self.myPosY
        myDirect = self.myDirect

        ax = self.mapFig.add_subplot(111)
        ax.cla()
        ax.set_xlim(-fieldWidth, fieldWidth)
        ax.set_ylim(-fieldHeight, fieldHeight)

        r1 = patches.Rectangle(xy=(-centerBoxWidth / 2,-centerBoxHeight / 2),
                               width=centerBoxWidth, height=centerBoxHeight,
                               ec='#000000', fill=False)
        r2 = patches.Rectangle(xy=(-otherBoxDistance - otherBoxWidth / 2,
                                   -otherBoxDistance - otherBoxHeight / 2),
                               width=otherBoxWidth, height=otherBoxHeight,
                               ec='#000000', fill=False)
        r3 = patches.Rectangle(xy=(+otherBoxDistance - otherBoxWidth / 2,
                                   -otherBoxDistance - otherBoxHeight / 2),
                               width=otherBoxWidth, height=otherBoxHeight,
                               ec='#000000', fill=False)
        r4 = patches.Rectangle(xy=(-otherBoxDistance - otherBoxWidth / 2,
                                   +otherBoxDistance - otherBoxHeight / 2),
                               width=otherBoxWidth, height=otherBoxHeight,
                               ec='#000000', fill=False)
        r5 = patches.Rectangle(xy=(+otherBoxDistance - otherBoxWidth / 2,
                                   +otherBoxDistance - otherBoxHeight / 2),
                               width=otherBoxWidth, height=otherBoxHeight,
                            ec='#000000', fill=False)

        a1 = patches.Arrow(myPosX, myPosY,
                           np.cos(myDirect) * 15, np.sin(myDirect) * 15, 10, ec='#0000FF')

        c1 = patches.Circle(xy=(myPosX, myPosY), radius=6, ec='#0000FF')

        ax.add_patch(r1)
        ax.add_patch(r2)
        ax.add_patch(r3)
        ax.add_patch(r4)
        ax.add_patch(r5)
        ax.add_patch(a1)
        ax.add_patch(c1)

        x = np.linspace(-fieldWidth, fieldWidth - 1, fieldWidth * 2)
        y = x + fieldHeight
        ax.plot(x, y, "r-")

        x = np.linspace(-fieldWidth, fieldWidth - 1, fieldWidth * 2)
        y = x - fieldHeight
        ax.plot(x, y, "r-")

        x = np.linspace(-fieldWidth, fieldWidth - 1, fieldWidth * 2)
        y = -x + fieldHeight
        ax.plot(x, y, "r-")

        x = np.linspace(-fieldWidth, fieldWidth - 1, fieldWidth * 2)
        y = -x - fieldHeight
        ax.plot(x, y, "r-")

    def strategy(self):
        r = rospy.Rate(1) # change speed fps

        target_speed = 0
        target_turn = 0
        control_speed = 0
        control_turn = 0

        # Main Loop --->
        while not rospy.is_shutdown():
            plt.pause(0.05)
            twist = self.calcTwist()
            #print(twist)

            r.sleep()

        # Main Loop <---
        
if __name__ == '__main__':
    rospy.init_node('seigo_run')
    bot = SeigoBot('Seigo')
    bot.strategy()

