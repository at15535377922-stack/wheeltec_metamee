#!/usr/bin/env python
# -*- coding: utf-8 -*-

import rospy
import json
import os
from geometry_msgs.msg import Pose2D
from std_msgs.msg import String
import logging
logger = logging.getLogger(__name__)

class Waypoint(object):
    def __init__(self, name="", x=0.0, y=0.0, theta=0.0):
        self.name = name
        self.x = x
        self.y = y
        self.theta = theta

    def to_dict(self):
        return {
            'name': self.name,
            'x': self.x,
            'y': self.y,
            'theta': self.theta
        }

    @classmethod
    def from_dict(cls, data):
        return cls(
            name=data.get('name', ''),
            x=data.get('x', 0.0),
            y=data.get('y', 0.0),
            theta=data.get('theta', 0.0)
        )
    
    def __eq__(self, other):
        if not isinstance(other, Waypoint):
            return False
        return self.x == other.x and self.y == other.y and self.theta == other.theta and self.name == other.name

    def __hash__(self):
        return hash((self.x, self.y, self.theta, self.name))

class WaypointsManager(object):
    def __init__(self):
        # Initialize publisher and subscriber
        self.pub = rospy.Publisher('/metamee/waypoints', String, latch = True, queue_size=10)
        self.sub = rospy.Subscriber('/metamee/waypoints', String, self.waypoints_callback)
        
        # Initialize waypoints cache
        self.waypoints_cache = []
        self.json_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", 'map', 'waypoints.json')
        
        # Load waypoints from json file on startup
        self.load_waypoints()
        
        logging.info("Waypoints manager initialized")
        
    def load_waypoints(self):
        """Load waypoints from json file"""
        try:
            if os.path.exists(self.json_path):
                with open(self.json_path, 'r') as f:
                    data = json.load(f)
                    self.waypoints_cache = [Waypoint.from_dict(wp) for wp in data]
                
                    cache_data = [wp.to_dict() for wp in self.waypoints_cache]
                    cache_msg = String()
                    cache_msg.data = json.dumps(cache_data)
                    self.pub.publish(cache_msg)
                    logging.info("Published cached waypoints")
                logging.info("Loaded waypoints from json file")
            else:
                self.waypoints_cache = []
                logging.info("No waypoints file found, starting with empty cache")
        except Exception as e:
            logging.error("Error loading waypoints: %s", str(e))
            self.waypoints_cache = []
    
    def save_waypoints(self):
        """保存导航点到文件"""
        try:
            waypoints_data = []
            for waypoint in self.waypoints_cache:
                waypoint_data = {
                    'name': waypoint.name,
                    'x': waypoint.x,
                    'y': waypoint.y,
                    'theta': waypoint.theta,
                }
                waypoints_data.append(waypoint_data)
            
            with open(self.json_path, 'w') as f:
                json.dump(waypoints_data, f, indent=4, ensure_ascii=False)
            return True
        except Exception as e:
            logging.error("Error saving waypoints: %s", str(e))
            return False
    
    def waypoints_callback(self, msg):
        """Handle incoming waypoints messages"""
        try:
            # Parse incoming JSON string
            new_waypoints_data = json.loads(msg.data)
            new_waypoints = [Waypoint.from_dict(wp) for wp in new_waypoints_data]
            
            # Check if waypoints are different from cache
            if set(new_waypoints) != set(self.waypoints_cache):
                if not new_waypoints:  # If incoming message is empty
                    # Use cache to update the topic
                    if self.waypoints_cache:
                        cache_data = [wp.to_dict() for wp in self.waypoints_cache]
                        cache_msg = String()
                        cache_msg.data = json.dumps(cache_data)
                        self.pub.publish(cache_msg)
                        logging.info("Published cached waypoints")
                else:
                    # Update cache with new waypoints and save to json
                    self.waypoints_cache = new_waypoints
                    self.save_waypoints()
                    logging.info("Updated waypoints cache and saved to json")
        except ValueError as e:
            logging.error("Error parsing waypoints JSON: %s", str(e))
        except Exception as e:
            logging.error("Error processing waypoints: %s", str(e))

def main():
    try:
        # If directly running this file, then initialize node
        rospy.init_node('waypoints_manager')
        waypoints_manager = WaypointsManager()
        rospy.spin()
    except rospy.ROSInterruptException:
        pass

if __name__ == '__main__':
    main()


"""

导航点信息：
waypoints.json
[
    {
        "name": "导航点1",
        "x": -2.55,
        "y": -2.1,
        "theta": 1.423
    },
    {
        "name": "导航点2",
        "x": -4.5,
        "y": -2.2,
        "theta": 2.909
    }
]

"""