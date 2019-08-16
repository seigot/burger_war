#!/usr/bin/env python
# -*- coding: utf-8 -*-
import rospy
import random

from std_msgs.msg import String
from geometry_msgs.msg import Twist
from geometry_msgs.msg import PoseWithCovarianceStamped
import tf
from sensor_msgs.msg import LaserScan
from sensor_msgs.msg import Image
from sensor_msgs.msg import JointState
from cv_bridge import CvBridge, CvBridgeError
from std_msgs.msg import String
from enum import Enum
import cv2
import enemyTable as eT
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.patches as patches
import time
import actionlib
from move_base_msgs.msg import MoveBaseAction, MoveBaseGoal
from nav_msgs.msg import Odometry
import actionlib_msgs
import json

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

# color definition
RED   = 1
GREEN = 2
BLUE  = 3

# target angle init value
COLOR_TARGET_ANGLE_INIT_VAL = -360
# distance to enemy init value
DISTANCE_TO_ENEMY_INIT_VAL = 1000

# PI
PI = 3.1415

# FIND_ENEMY status
FIND_ENEMY_SEARCH = 0
FIND_ENEMY_FOUND = 1
FIND_ENEMY_WAIT = 2
FIND_ENEMY_LOOKON = 3

# SNIPE_MODE_KEEP_DISTANCE_FROM_ENEMY_THRESHOLD(m)
DISTANCE_KEEP_TO_ENEMY_THRESHOLD = 1.5
DISTANCE_KEEP_TO_ENEMY_THRESHOLD_WHEN_LOWWER_SCORE = 0.45

# robot running coordinate in SEARCH MODE
search_coordinate = np.array([
        # x, y, th
        [0.5, 0, PI],
        [0.9, 0, PI],
        [0.9, -0.5, PI],
        [0.9, 0.5, PI],
        [0.9, 0, PI],
        [0, 0.5, -1*PI/2],
        [0, 0.5, 0],
        [0, 0.5, PI],
        [-0.5, 0, 0],
        [-0.9, 0, 0],
        [-0.9, 0.5, 0],
        [-0.9, -0.5, 0],
        [-0.9, 0, 0],
        [0, -0.5, PI/2],
        [0, -0.5, 0],
        [0, -0.5, PI],
        [0, -0.5, PI/4]
])

# robot running coordinate in SEARCH MODE
basic_coordinate = np.array([
    # x, y, th
    [-0.9, 0.5, 0],
    [-0.9, -0.5, 0],
    [-0.9, 0.0, 0],
    [-0.4, 0.0, 0],
    [-0.9, 0.0, 0],
    [0, -0.5, 0],
    [0, -0.5, PI],
    [0, -0.5, PI/2],
    [0, -1.2, PI/2]]
)

class ActMode(Enum):
    SEARCH = 1
    SNIPE  = 2
    ESCAPE = 3
    ATTACK = 4
    BASIC  = 5

    # (start) BASIC --> SNIPE --> SEARCH or ESCAPE or ATTACK --> (end)

class SeigoBot():
    myPosX = 0
    myPosY = -150
    myDirect = np.pi / 2
    lidarFig = plt.figure(figsize=(5,5))
    mapFig = plt.figure(figsize=(5,5))
    time_start = 0
    f_Is_lowwer_score = False
    f_Is_cancel_published = False
    basic_mode_process_step_idx = 0 # process step in basic MODE
    search_mode_process_step_idx = -1 # process step in search MODE
    
    def __init__(self, bot_name):
        # bot name
        robot_name = rospy.get_param('~robot_name') # red_bot or blue_bot
        self.name = robot_name
        print("self.name", self.name)
        
        # velocity publisher
        self.vel_pub = rospy.Publisher('cmd_vel', Twist,queue_size=1)
        # navigation publisher
        self.client = actionlib.SimpleActionClient('move_base',MoveBaseAction)

        # Lidar
        self.scan = LaserScan()
        topicname_scan = "/" + self.name + "/scan"
        self.lidar_sub = rospy.Subscriber(topicname_scan, LaserScan, self.lidarCallback)
        self.front_distance = DISTANCE_TO_ENEMY_INIT_VAL # init
        self.front_scan = DISTANCE_TO_ENEMY_INIT_VAL
 
        # usb camera
        self.img = None
        self.camera_preview = True
        self.bridge = CvBridge()
        topicname_image_raw = "/" + self.name + "/image_raw"
        self.image_sub = rospy.Subscriber(topicname_image_raw, Image, self.imageCallback)
        self.red_angle = COLOR_TARGET_ANGLE_INIT_VAL # init
        self.blue_angle = COLOR_TARGET_ANGLE_INIT_VAL # init
        self.green_angle = COLOR_TARGET_ANGLE_INIT_VAL # init
        self.red_distance = DISTANCE_TO_ENEMY_INIT_VAL # init

        # FIND_ENEMY status 
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

        # war status
        topicname_war_state = "/" + self.name + "/war_state"
	self.war_state = rospy.Subscriber(topicname_war_state, String, self.stateCallback)
        self.my_score = 0
        self.enemy_score = 0
        self.act_mode = ActMode.BASIC

        # odom
        topicname_odom = "/" + self.name + "/odom"
	self.odom = rospy.Subscriber(topicname_odom, Odometry, self.odomCallback)

        # amcl pose
        topicname_amcl_pose = "/" + self.name + "/amcl_pose"
	self.amcl_pose = rospy.Subscriber(topicname_amcl_pose, PoseWithCovarianceStamped, self.AmclPoseCallback)
        
        # time
        self.time_start = time.time()

    def odomCallback(self, data):
        # print(data.pose.pose.position.x,data.pose.pose.position.y,data.pose.pose.orientation.z,data.pose.pose.orientation.w)
        e = tf.transformations.euler_from_quaternion((data.pose.pose.orientation.x, data.pose.pose.orientation.y, data.pose.pose.orientation.z, data.pose.pose.orientation.w))
        # print(e[2] / (2 * np.pi) * 360)
        self.myDirect = e # rad

    def AmclPoseCallback(self, data):
        self.myPosX = data.pose.pose.position.x
        self.myPosY = data.pose.pose.position.y
        # print(self.myPosX, self.myPosY)

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

    def getElapsedTime(self):
        time_current = time.time()
        elapsed_time = time_current - self.time_start
        return elapsed_time
        
    # Ref: https://hotblackrobotics.github.io/en/blog/2018/01/29/action-client-py/
    # Ref: https://github.com/hotic06/burger_war/blob/master/burger_war/scripts/navirun.py
    # RESPECT @hotic06
    # do following command first.
    #   $ roslaunch burger_navigation multi_robot_navigation_run.launch
    def setGoal(self,x,y,yaw):
        self.client.wait_for_server()

        goal = MoveBaseGoal()
        goal.target_pose.header.frame_id = self.name + "/map"
        goal.target_pose.header.stamp = rospy.Time.now()
        goal.target_pose.pose.position.x = x
        goal.target_pose.pose.position.y = y

        # Euler to Quartanion
        q=tf.transformations.quaternion_from_euler(0,0,yaw)        
        goal.target_pose.pose.orientation.x = q[0]
        goal.target_pose.pose.orientation.y = q[1]
        goal.target_pose.pose.orientation.z = q[2]
        goal.target_pose.pose.orientation.w = q[3]

        self.client.send_goal(goal)
        wait = self.client.wait_for_result()
        if not wait:
            rospy.logerr("Action server not available!")
            rospy.signal_shutdown("Action server not available!")
        else:
            get_result = self.client.get_result()
            print("wait", wait, "get_result", get_result)

        if self.f_Is_cancel_published == True:
            self.f_Is_cancel_published = False
            return -1

        return 0

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
        # self.front_distance = self.scan.ranges[0]
        self.front_distance = min(min(self.scan.ranges[0:10]),min(self.scan.ranges[350:359]))
        self.front_scan = (sum(self.scan.ranges[0:4])+sum(self.scan.ranges[355:359])) / 10

    def find_rect_of_target_color(self, image, color_type): # r:0, g:1, b:2
        hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV_FULL)
        h = hsv[:, :, 0]
        s = hsv[:, :, 1]

        # red detection
        if color_type == RED:
            mask = np.zeros(h.shape, dtype=np.uint8)
            mask[((h < 20) | (h > 200)) & (s > 128)] = 255

        # blue detection
        if color_type == BLUE:
            lower_blue = np.array([130, 50, 50])
            upper_blue = np.array([200, 255, 255])
            mask = cv2.inRange(hsv, lower_blue, upper_blue)

        # green detection
        if color_type == GREEN:
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
        rects = self.find_rect_of_target_color(frame, RED)
        if len(rects) > 0:
            rect = max(rects, key=(lambda x: x[2] * x[3]))
            if rect[3] > 10: # if red circle is enemy one (check if not noise)
                cv2.rectangle(frame, tuple(rect[0:2]), tuple(rect[0:2] + rect[2:4]), (0, 0, 255), thickness=2)
                # angle(rad)
                tmp_angle = ((rect[0]+rect[0]+rect[2])/2-(img_w/2)) *0.077
                self.red_angle = tmp_angle * np.pi / 180
                # distance (m)
                if rect[1] < len(eT.enemyTable):
                    self.red_distance = eT.enemyTable[rect[1]] if eT.enemyTable[rect[1]] > 0 else 1
            else:
                self.red_distance = 1
                
            # print ("red_angle", tmp_angle, self.red_angle, self.red_distance)
            # print ( tmp_angle )
            redFound = True
            self.trackEnemy(rect)
        else:
            self.red_angle = COLOR_TARGET_ANGLE_INIT_VAL

        # green
        rects = self.find_rect_of_target_color(frame, GREEN)
        if len(rects) > 0:
            rect = max(rects, key=(lambda x: x[2] * x[3]))
            cv2.rectangle(frame, tuple(rect[0:2]), tuple(rect[0:2] + rect[2:4]), (0, 0, 255), thickness=2)
            # angle(rad)
            tmp_angle = ((rect[0]+rect[0]+rect[2])/2-(img_w/2)) *0.077
            self.green_angle = tmp_angle * np.pi / 180
            # print ("green_angle", tmp_angle, self.green_angle )
            # print ( tmp_angle )
            if  redFound is False:
                greenFound = True
                self.trackEnemy(rect)
        else:
            self.green_angle = COLOR_TARGET_ANGLE_INIT_VAL

        if redFound is False and greenFound is False:
            self.trackEnemy(None)

        # blue
        rects = self.find_rect_of_target_color(frame, BLUE)
        if len(rects) > 0:
            rect = max(rects, key=(lambda x: x[2] * x[3]))
            cv2.rectangle(frame, tuple(rect[0:2]), tuple(rect[0:2] + rect[2:4]), (0, 0, 255), thickness=2)
            # angle(rad)
            tmp_angle = ((rect[0]+rect[0]+rect[2])/2-(img_w/2)) *0.077
            self.blue_angle = tmp_angle * np.pi / 180
            # print ("blue_angle", tmp_angle, self.blue_angle )
        else:
            self.blue_angle = COLOR_TARGET_ANGLE_INIT_VAL

        #    if self.camera_preview:
        # print("image show")
        cv2.imshow("Image window", frame)
        cv2.waitKey(1)

    def stateCallback(self, state):
        # print(state.data)
        dic = json.loads(state.data)
        tmp = int(dic["scores"]["r"])
        self.my_score = tmp
        self.enemy_score = int(dic["scores"]["b"])
        # update which bot is higher score
        if self.my_score <= self.enemy_score:
            self.f_Is_lowwer_score = True
        else:
            self.f_Is_lowwer_score = False
            
        print("---")
        print("f_Is_lowwer_score", self.f_Is_lowwer_score)
        print("my_sore", self.my_score)
        print("enemy_score", self.enemy_score)
        print("elapsed_time", self.getElapsedTime())
        
    def approachToMarker(self):
        x = 0
        th = 0
        twist = Twist()
        twist.linear.x = x; twist.linear.y = 0; twist.linear.z = 0
        twist.angular.x = 0; twist.angular.y = 0; twist.angular.z = th
        return twist

    def keepMarkerToCenter(self, color_type, distance_threshold):

        # keep center to enemy
        angle = COLOR_TARGET_ANGLE_INIT_VAL
	if color_type == RED:
            angle = self.red_angle
	elif color_type == GREEN:
            angle = self.green_angle
	elif color_type == BLUE:
            angle = self.blue_angle
        else:
            print("invalid color_type", color_type)
            return

        if angle == COLOR_TARGET_ANGLE_INIT_VAL:
            return -1

        # keep distance to enemy when both red/green color found
        if self.red_angle != COLOR_TARGET_ANGLE_INIT_VAL and self.green_angle != COLOR_TARGET_ANGLE_INIT_VAL:
            _x = self.red_distance - distance_threshold
        else:
            _x = 0
            
        x = _x
        th = angle * (-1) # rad/s
        twist = Twist()
        twist.linear.x = x; twist.linear.y = 0; twist.linear.z = 0
        twist.angular.x = 0; twist.angular.y = 0; twist.angular.z = th
        self.vel_pub.publish(twist)

        return 0

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
                if self.scan.ranges is None or self.moving is True or self.front_distance == DISTANCE_TO_ENEMY_INIT_VAL:
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

    def getTwist(self, _x, _th):
        twist = Twist()
        x = _x
        th = _th
        twist.linear.x = x; twist.linear.y = 0; twist.linear.z = 0
        twist.angular.x = 0; twist.angular.y = 0; twist.angular.z = th        
        return twist

    def func_search_neighbourhood(self, p0, ps):
        L = np.array([])
        for i in range(ps.shape[0]):
            norm = np.sqrt( (ps[i][0] - p0[0])*(ps[i][0] - p0[0]) +
                            (ps[i][1] - p0[1])*(ps[i][1] - p0[1]) )
            L = np.append(L, norm)
        return np.argmin(L) ,ps[np.argmin(L)]

    def func_init(self):
        print("func_init")
        twist = Twist()
        r = rospy.Rate(1) # change speed fps
        time.sleep(1.000) # wait for init complete

        print("!!!!!! !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!! !!!!!!")
        print("!                                                     !")
        print("! do following command first for navigation           !")
        print("! $ roslaunch burger_navigation multi_robot_navigation_run.launch !")
        print("! $ rosservice call /gazebo/reset_simulation {}       !")
        print("!                                                     !")
        print("!!!!!! !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!! !!!!!!")
        print("")
        
        ElapsedTime = self.getElapsedTime()
        print("ElapsedTime",ElapsedTime)

        return
    
    def func_basic(self):
        print("func_basic")
        twist = Twist()

        # init search process
        if self.basic_mode_process_step_idx < 0: # -1
            return -1
        elif self.basic_mode_process_step_idx >= len(basic_coordinate):
            self.act_mode = ActMode.SNIPE # transition to SNIPE
            return 0

        # basic
        NextGoal_coor = basic_coordinate[ self.basic_mode_process_step_idx ]
        _x = NextGoal_coor[0]
        _y = NextGoal_coor[1]
        _th = NextGoal_coor[2]
        ret = self.setGoal(_x, _y, _th)
        if ret == 0:
            self.basic_mode_process_step_idx += 1
        else:
            print("setGoal ret:", ret)

        return 0

    def func_snipe(self):
        print("func_snipe")
        twist = Twist()

        # keep sniping..
        twist = self.getTwist(0, -1*3.1415/2)
        self.vel_pub.publish(twist)
        time.sleep(1.25)

        cnt = 0
        rate=1500
        r = rospy.Rate(rate) # change speed fps
        while not rospy.is_shutdown():
            if cnt%2 == 0:
                twist = self.getTwist(0, 3.1415/2)
            else: # if cnt%2 == 1:
                twist = self.getTwist(0, -1*3.1415/2)
            self.vel_pub.publish(twist)
            for i in range(rate):

                # keep enemy marker (RED/GREEN) to center position
                ret = self.keepMarkerToCenter(RED, DISTANCE_KEEP_TO_ENEMY_THRESHOLD)
                if ret == -1:
                    # if RED marker not found, keep GREEN color to center
                    ret = self.keepMarkerToCenter(GREEN, None)
                    #if ret == -1:
                    #print("no color target found...")
                r.sleep()
            cnt+=1

 	    #if self.getElapsedTime() > 120 and self.f_Is_lowwer_score == True:
            # [TODO] debug
 	    if self.getElapsedTime() > 60: # for Debug
                self.act_mode = ActMode.ATTACK
                return
            
        #self.act_mode = ActMode.SEARCH # transition to ESCAPE
        #self.act_mode = ActMode.ESCAPE # transition to ESCAPE
        #self.act_mode = ActMode.ATTACK # transition to ATTACK
        return

    def func_search(self):
        print("func_search")

        # [TODO] if red/green found, ATTACK mode

        # init search process
        if self.search_mode_process_step_idx < 0: # -1
            # get nearrest position
            current_coor = np.array([self.myPosX, self.myPosY])
            idx, nearrest_coor = self.func_search_neighbourhood(current_coor, search_coordinate)
            print( idx, nearrest_coor[0], nearrest_coor[1], nearrest_coor[2] ) # idx, (x, y, th)
            self.search_mode_process_step_idx = idx
        elif self.search_mode_process_step_idx >= len(search_coordinate):
            self.search_mode_process_step_idx = 0

        # search 
        NextGoal_coor = search_coordinate[ self.search_mode_process_step_idx ]
        _x = NextGoal_coor[0]
        _y = NextGoal_coor[1]
        _th = NextGoal_coor[2]
        ret = self.setGoal(_x, _y, _th)
        if ret == 0:
            self.search_mode_process_step_idx += 1
        else:
            print("setGoal ret:", ret)

        return 0
    
    def func_escape(self):
        print("func_escape")        
        # [TODO]
        return

    def func_attack(self):
        print("func_attack")

        cnt = 0
        rate=1500
        r = rospy.Rate(rate) # change speed fps
        while not rospy.is_shutdown():
            # search 
            if cnt%2 == 0:
                twist = self.getTwist(0, 3.1415*2/3)
            else: # if cnt%2 == 1:
                twist = self.getTwist(0, -1*3.1415*2/3)
            self.vel_pub.publish(twist)

            # dog fight !!!
            for i in range(rate):
                # Is there something ahead?
                if np.max(self.scan.ranges[0:5]) < 1.0 and np.max(self.scan.ranges[355:359]) < 1.0:
                    distance_threshold = DISTANCE_KEEP_TO_ENEMY_THRESHOLD
                else:
                    distance_threshold = DISTANCE_KEEP_TO_ENEMY_THRESHOLD_WHEN_LOWWER_SCORE
                # keep enemy marker (RED/GREEN) to center position
                ret = self.keepMarkerToCenter(RED, distance_threshold)
                if ret == -1:
                    # if RED marker not found, keep GREEN color to center
                    ret = self.keepMarkerToCenter(GREEN, None)
                    if ret == -1:
                        self.act_mode = ActMode.SEARCH
                        self.search_mode_process_step_idx = -1
                        return

                r.sleep()
            cnt+=1

        return

    def strategy(self):
        target_speed = 0
        target_turn = 0
        control_speed = 0
        control_turn = 0
        
        # Main Loop --->
        self.func_init()
        r = rospy.Rate(1500) # change speed fps
        while not rospy.is_shutdown():
            print("act_mode: ", self.act_mode)

            if self.act_mode == ActMode.BASIC:
                self.func_basic()
            elif self.act_mode == ActMode.SNIPE: # SNIPE
                self.func_snipe()
            elif self.act_mode == ActMode.SEARCH:  # SEARCH
                self.func_search()
            elif self.act_mode == ActMode.ESCAPE: # ESCAPE
                self.func_escape()
            elif self.act_mode == ActMode.ATTACK: # ATTACK
                self.func_attack()
            else:
                print("act_mode: ", self.act_mode)
                
            r.sleep()
        # Main Loop <---
        
if __name__ == '__main__':

    rospy.init_node('bot_name')
    bot = SeigoBot('bot_name')
    bot.strategy()

