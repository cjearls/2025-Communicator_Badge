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

#
def find_best_frame(delta_array, frame_width, frame_height, x_width, y_height):
    max_x = 0
    max_y = 0
    delta_max = 0
    for x in range(x_width):
        if x - frame_width/2 < 0 or x + frame_width/2 > x_width-1:
            # Skip if we're going to try invalid indices to access the array
            continue
        for y in range(y_height):
            if y - frame_height/2 < 0 or y + frame_height/2 > y_height - 1:
                # Skip if we're going to try invalid indices to access the array
                continue

            # Add up all the pixel delta sums
            delta_sum = 0
            for column_index in range(int(x-frame_width/2), int(x+frame_width/2)):
                for row_index in range(int(y-frame_height/2), int(y+frame_height/2)):
                    delta_sum += delta_array[column_index][row_index]

            if delta_sum > delta_max:
                delta_max = delta_sum
                max_x = x
                max_y = y
            
    return (max_x, max_y)

# This finds areas that have the most variance by checking the average disatnce between a pixel and its neighbors
def get_iteration_deltas(iteration_array):
    delta_array = list()
    for column_index in range(len(iteration_array)):
        delta_array.append(list())
        for row_index in range(len(iteration_array[column_index])):
            # Calculate the average difference between this iteration count and the iteration counts surrounding
            iteration_value = iteration_array[column_index][row_index]
            delta_sum = 0
            if column_index == 0 or column_index == (len(iteration_array)-1) or row_index == 0 or row_index == (len(iteration_array[column_index])-1):
                # Don't consider the borders for zooming at all
                pass
            else:
                # add the difference values for neighboring pixels in x and y
                delta_sum += abs(iteration_value - iteration_array[column_index+1][row_index])
                delta_sum += abs(iteration_value - iteration_array[column_index-1][row_index])
                delta_sum += abs(iteration_value - iteration_array[column_index][row_index+1])
                delta_sum += abs(iteration_value - iteration_array[column_index][row_index-1])
            # add the delta average to the array for later processing
            delta_array[column_index].append(delta_sum/4)

    return delta_array

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
            return (iteration, z)
    return (iterations+1, z)

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
                z = (0.0, 0.0)
                c = (graph_x/self.zoom_factor+self.zoom_center_x, graph_y/self.zoom_factor + self.zoom_center_y)
                (iterations, z_result) = mandelbrot_iter(z, c, self.bound_number, self.mandelbrot_iterations)

                # Log the iterations needed so we can choose an interesting place to zoom next time
                self.iteration_array[x][self.y_height-1-y] = iterations

                # Then convert it to the display's RGB565 format
                color_24bit = cycle_colors(iterations, self.mandelbrot_iterations+1)
                color =  generate_565_color((color_24bit>>16)&0xFF, (color_24bit>>8)&0xFF, color_24bit&0xFF)
                
                #Then get the upper and lower bytes of the color for writing to the buffer
                upper_color_byte = color >> 8
                lower_color_byte = color & 0xFF
                self.canvas_buffer[2*x+self.x_width*2*y] = lower_color_byte
                self.canvas_buffer[2*x+1+self.x_width*2*y] = upper_color_byte
            # By setting the buffer, we tell the display to update with the new data we've written to it
            self.canvas.set_buffer(self.canvas_buffer,self.x_width,self.y_height,lvgl.COLOR_FORMAT.RGB565)

        # Get the deltas of each pixel with its neighbors and put them in an array
        delta_array = get_iteration_deltas(self.iteration_array)
        # # Get the pixel with the largest delta and zoom in on it
        # max_x_index = 0
        # max_y_index = 0
        # max_delta = 0
        # for x_index in range(len(delta_array)):
        #     for y_index in range(len(delta_array[x_index])):
        #         if delta_array[x_index][y_index] > max_delta:
        #             max_delta = delta_array[x_index][y_index]
        #             max_x_index = x_index
        #             max_y_index = y_index
        # self.zoom_center_x = self.zoom_center_x + (max_x_index - self.x_width/2)/self.zoom_factor
        # self.zoom_center_y = self.zoom_center_y + (max_y_index - self.y_height/2)/self.zoom_factor

        # Get the next frame center with the largest delta for a better photo
        frame_width = self.x_width/self.zoom_factor
        frame_height = self.y_height/self.zoom_factor
        (new_zoom_center_x, new_zoom_center_y) = find_best_frame(delta_array, frame_width, frame_height, self.x_width, self.y_height)
        self.zoom_center_x = self.zoom_center_x + (new_zoom_center_x - self.x_width/2)/self.zoom_factor
        self.zoom_center_y = self.zoom_center_y + (new_zoom_center_y - self.y_height/2)/self.zoom_factor

        # Increase the zoom and go again
        self.zoom_factor *= self.zoom_scale_factor


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

        # This tells where on the fractal we'll be rendering
        self.zoom_center_x = float(-0.74548)
        self.zoom_center_y = float(0.11669)
        self.zoom_factor = float(500_000.0)
        # self.zoom_factor = float(100.0)
        self.zoom_scale_factor = 4.0
        # This is the threshold we use to test how many iterations it takes to escape, so we can keep rendering pretty stuff
        self.bound_number = 10.0**20
        # self.bound_number = 10.0**5
        # This is the number of times we run mandelbrot to see if it escapes the bounds
        self.mandelbrot_iterations = 0xFE
        # self.mandelbrot_iterations = 0x08
        # This is going to be used to determine where the most interesting places to zoom into are
        self.iteration_array = list()
        for column in range(self.x_width):
            column_values = list()
            for row in range(self.y_height):
                column_values.append(0)
            self.iteration_array.append(column_values)