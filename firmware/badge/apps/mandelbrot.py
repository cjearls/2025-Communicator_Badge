"""
This is an example application showing how to use the canvas to control pixels to create a shifting rainbow.
From here, try some of the other canvas-related functions, like the ones to draw lines and arcs.
"""

import uasyncio as aio  # type: ignore

from apps.base_app import BaseApp
from net.net import register_receiver, send, BROADCAST_ADDRESS
from net.protocols import Protocol, NetworkFrame
from ui.page import Page
import ui.styles as styles
import lvgl

# This cycles through red, green, and blue with 8 bits per color channel on a scalable counter_value
def cycle_colors(counter_value, max_counter):
    red = 0
    green = 0
    blue = 0
    threshold_count = max_counter/3
    threshold0 = threshold_count
    threshold1 = 2*max_counter/3

    # There are three parts of the cycle:
    if counter_value >= 0 and counter_value < threshold0:
        # Transition the colors from black to red
        red = counter_value*0xFF/(threshold_count)
    elif counter_value >= threshold0 and counter_value < threshold1:
        # Transition the colors from green to blue
        red = 0xFF-(counter_value-threshold0)*0xFF/(threshold_count)
        green = (counter_value-threshold0)*0xFF/(threshold_count)
    elif counter_value < max_counter:
        # Transition the colors from green to blue
        green = 0xFF-(counter_value-threshold1)*0xFF/(threshold_count)
        blue = (counter_value-threshold1)*0xFF/(threshold_count)
    else:
        blue = 0xFF

    # Create the 24-bit color by combining the component colors
    new_color = (int(red)<<16) | (int(green)<<8) | int(blue)
    return new_color

# This translates from a 24-bit color space to a 16-bit color space, where red and blue are 5 bits and green is 6 bits
def generate_565_color(red_byte, green_byte, blue_byte):
    # Mask and shift each color to the correct place
    return ((red_byte&0xF8)<<8) | ((green_byte&0xFC)<<3) | ((blue_byte&0xF8)>>3)

# Calculate an iteration of the mandelbrot
def mandelbrot(z, c):
    # z_real^2 + z_imag^2 + c_real
    new_z_real = z[0] * z[0] + c[0] - z[1] * z[1]
    # 2*z_imag*z_real + c_imag
    new_z_imag = 2*z[0]*z[1] + c[1]
    return (new_z_real, new_z_imag)

# Run the mandelbrot calculation several times and returns how many iterations needed to exceed 2 or iterations+1 if it never does so
def mandelbrot_iter(z, c, bound_number, iterations):
    for iteration in range(iterations):
        z = mandelbrot(z, c)
        if z[0] > bound_number or z[0] < -bound_number or z[1] > bound_number or z[1] < -bound_number:
            return iteration
    return iterations+1

class App(BaseApp):
    """Define a new app to run on the badge."""

    def run_foreground(self):
        """Run one pass of the app's behavior when it is in the foreground (has keyboard input and control of the screen).
        You do not need to loop here, and the app will sleep for at least self.foreground_sleep_ms milliseconds between calls.
        Don't block in this function, for it will block reading the radio and keyboard.
        If the app only runs in the background, you can delete this method.
        """

        # Loop through the pixels
        for x in range(self.x_width):

            # This is the x value for the graph
            graph_x = x - self.x_width/2

            for y in range(self.y_height):
                # This is the y value for the graph
                graph_y = self.y_height/2 - y

                # For each pixel in the column, write the upper and lower bytes
                if graph_x == 0 or graph_y == 0:
                    self.canvas_buffer[2*x+self.x_width*2*y] = 0 
                    self.canvas_buffer[2*x+1+self.x_width*2*y] = 0
                else:
                    z = (0.0, 0.0)
                    c = (2.0*graph_x/float(self.y_height), 2.0*graph_y/float(self.y_height))
                    iterations = mandelbrot_iter(z, c, 10.0**20, 0xFE)
                    # print("Mandelbrot iteration " + str(iteration) + " for c=" + str(c[0]) + ": z_real: " + str(z[0]) + ", z_imag: " + str(z[1]))
                    # Then convert it to the display's RGB565 format
                    color_24bit = cycle_colors(iterations, 0xFF)
                    color =  generate_565_color((color_24bit>>16)&0xFF, (color_24bit>>8)&0xFF, color_24bit&0xFF)
                    
                    #Then get the upper and lower bytes of the color for writing to the buffer
                    upper_color_byte = color >> 8
                    lower_color_byte = color & 0xFF
                    self.canvas_buffer[2*x+self.x_width*2*y] = lower_color_byte
                    self.canvas_buffer[2*x+1+self.x_width*2*y] = upper_color_byte
            # By setting the buffer, we tell the display to update with the new data we've written to it
            self.canvas.set_buffer(self.canvas_buffer,self.x_width,self.y_height,lvgl.COLOR_FORMAT.RGB565)

        # By setting the buffer, we tell the display to update with the new data we've written to it
        self.canvas.set_buffer(self.canvas_buffer,self.x_width,self.y_height,lvgl.COLOR_FORMAT.RGB565)

        # Listen for any of the functions keys to escape from the app
        if (
            self.badge.keyboard.f1()
            or self.badge.keyboard.f2()
            or self.badge.keyboard.f3()
            or self.badge.keyboard.f4()
            or self.badge.keyboard.f5()
        ):
            self.badge.display.clear()
            self.switch_to_background()

    def switch_to_foreground(self):
        """Set the app as the active foreground app.
        This will be called by the Menu when the app is selected.
        Any one-time logic to run when the app comes to the foreground (such as setting up the screen) should go here.
        If you don't have special transition logic, you can delete this method.
        """
        super().switch_to_foreground()
        
        # Get the active screen
        self.fullscreen = lvgl.obj(lvgl.screen_active())

        # This stores how far to shift the columns of colors while scrolling the screen
        self.pixel_shift = 0

        # The canvas is the object we're using to control the pixels on the screen
        self.canvas = lvgl.canvas(lvgl.screen_active())

        # These are the default dimensions of the screen
        self.x_width = 428
        self.y_height = 142
        # The screen's color format is RGB565, so there are 2 bytes per pixel
        self.bytes_per_pixel = 2

        # The canvas buffer stores the color data that is rendered to the screen
        self.canvas_buffer = bytearray(self.x_width*self.y_height*self.bytes_per_pixel)

        # Give the buffer to the canvas with the information it needs to make sense of the data
        self.canvas.set_buffer(self.canvas_buffer,self.x_width,self.y_height,lvgl.COLOR_FORMAT.RGB565)

        # Center the canvas on the screen
        self.canvas.center()