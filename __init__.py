import os
import time
import psutil as psutil
from os.path import dirname, exists
import subprocess


from adapt.intent import IntentBuilder
from mycroft import MycroftSkill, intent_handler, intent_file_handler
from mycroft.audio import wait_while_speaking, is_speaking
from mycroft.messagebus.message import Message
from mycroft.util import record, play_wav
from mycroft.util.parse import extract_datetime
from mycroft.util.time import now_local

# ffmpeg -an -f video4linux2 -s 640x480 -r 25 -i /dev/video0 -vcodec mpeg4 -vtag DIVX output.avi


class VideoRecord(MycroftSkill):
    def __init__(self):
        super(VideoRecord, self).__init__("VideoRecord")
        self.play_process = None
        self.record_process = None
        self.start_time = 0
        self.last_index = 24  # index of last pixel in countdowns

        self.settings["min_free_disk"] = 100  # min mb to leave free on disk
        self.settings["file_path"] = "/tmp/video-recording.mp4"
        self.settings["duration"] = -1  # default = unknown

    def remaining_time(self):
        return self.settings["duration"] - (now_local() -
                                            self.start_time).total_seconds()

    def has_free_disk_space(self):
        free_mb = psutil.disk_usage('/')[2] / 1024 / 1024
        return free_mb  - 10 > self.settings["min_free_disk"]

    @staticmethod
    def stop_process(process):
        if process.poll() is None:  # None means still running
            process.terminate()
            # No good reason to wait, plus it interferes with
            # how stop button on the Mark 1 operates.
            # process.wait()
            return True
        else:
            return False

    # Handle: "Delete recording"
    @intent_handler(IntentBuilder('').require('Delete').require('Recording'))
    def handle_delete(self, message):
        if not exists(self.settings["file_path"]):
            self.speak_dialog('video.record.no.recording')
        else:
            try:
                os.remove(self.settings["file_path"])
                self.speak_dialog('video.record.removed')
            except:
                pass

    # Standard Stop handler
    def stop(self):
        if self.record_process:
            self.end_recording()
            return True
        if self.play_process:
            self.end_playback()
            return True
        return False

    ######################################################################
    # Recording

    def video_record(self,file_path, duration):
        if duration <= 0:
            duration = 1
        
        # ffmpeg -an -y -f video4linux2 -s 640x480 -r 30 -i /dev/video0  -vframes 300 -vcodec mpeg4 output.avi
        return subprocess.Popen(
            ["ffmpeg", "-an", "-y", "-f", "video4linux2", "-s" ,"640x480", "-r", "30","-i", "/dev/video0","-vframes", str(30*duration), "-vcodec", "mpeg4", file_path])

    @intent_file_handler('record.video.intent')
    def handle_record(self, message):
        utterance = message.data.get('utterance')

        self.log.info("In handle record")

        # Calculate how long to record
        self.start_time = now_local()
        stop_time, _ = extract_datetime(utterance, lang=self.lang)
        self.settings["duration"] = (stop_time -
                                     self.start_time).total_seconds()
        self.log.info("recording duration:" + str(self.settings["duration"]) + " stop: " + str(stop_time) + " start: " + str(self.start_time))

        if self.settings["duration"] <= 0:
            self.settings["duration"] = 10  # default recording duration

        # Throw away any previous recording
        try:
            os.remove(self.settings["file_path"])
        except:
            pass

        if self.has_free_disk_space():
            record_for = nice_duration(self, self.settings["duration"],
                                       lang=self.lang)
            self.speak_dialog('video.record.start.duration',
                              {'duration': record_for})

            # Initiate recording
            wait_while_speaking()
            self.start_time = now_local()   # recalc after speaking completes
            self.record_process = self.video_record(self.settings["file_path"],int(self.settings["duration"]))
            self.last_index = 24
            self.schedule_repeating_event(self.recording_feedback, None, 1,
                                          name='RecordingFeedback')
        else:
            self.speak_dialog("audio.record.disk.full")

    def recording_feedback(self, message):
        if not self.record_process:
            self.end_recording()
            return

        # Verify there is still adequate disk space to continue recording
        if self.record_process.poll() is None:
            if not self.has_free_disk_space():
                # Out of space
                self.end_recording()
                self.speak_dialog("video.record.disk.full")
        else:
            # Recording ended for some reason
            self.end_recording()

    def end_recording(self):
        self.cancel_scheduled_event('RecordingFeedback')

        if self.record_process:
            # Stop recording
            self.stop_process(self.record_process)
            self.record_process = None
            # Calc actual recording duration
            self.settings["duration"] = (now_local() -  self.start_time).total_seconds()

    ######################################################################
    # Playback

    @intent_file_handler('playback.video.intent')
    def handle_play(self, message):
        if exists(self.settings["file_path"]):
            # Initialize for playback
            self.start_time = now_local()

            # Playback the recording, with visual countdown
            self.play_process = play_wav(self.settings["file_path"])
            self.enclosure.eyes_color(64, 255, 64)  # set color greenish
            self.last_index = 24
            self.schedule_repeating_event(self.playback_feedback, None, 1,
                                          name='PlaybackFeedback')
        else:
            self.speak_dialog('audio.record.no.recording')

    def playback_feedback(self, message):
        if not self.play_process or self.play_process.poll() is not None:
            self.end_playback()
            return

    def end_playback(self):
        self.cancel_scheduled_event('PlaybackFeedback')
        if self.play_process:
            self.stop_process(self.play_process)
            self.play_process = None


def create_skill():
    return VideoRecord()


##########################################################################
# TODO: Move to mycroft.util.format
from mycroft.util.format import pronounce_number


def nice_duration(self, duration, lang="en-us", speech=True):
    """ Convert duration in seconds to a nice spoken timespan

    Examples:
       duration = 60  ->  "1:00" or "one minute"
       duration = 163  ->  "2:43" or "two minutes forty three seconds"

    Args:
        duration: time, in seconds
        speech (bool): format for speech (True) or display (False)
    Returns:
        str: timespan as a string
    """

    # Do traditional rounding: 2.5->3, 3.5->4, plus this
    # helps in a few cases of where calculations generate
    # times like 2:59:59.9 instead of 3:00.
    duration += 0.5

    days = int(duration // 86400)
    hours = int(duration // 3600 % 24)
    minutes = int(duration // 60 % 60)
    seconds = int(duration % 60)

    if speech:
        out = ""
        if days > 0:
            out += pronounce_number(days, lang) + " "
            if days == 1:
                out += self.translate("day")
            else:
                out += self.translate("days")
            out += " "
        if hours > 0:
            if out:
                out += " "
            out += pronounce_number(hours, lang) + " "
            if hours == 1:
                out += self.translate("hour")
            else:
                out += self.translate("hours")
        if minutes > 0:
            if out:
                out += " "
            out += pronounce_number(minutes, lang) + " "
            if minutes == 1:
                out += self.translate("minute")
            else:
                out += self.translate("minutes")
        if seconds > 0:
            if out:
                out += " "
            out += pronounce_number(seconds, lang) + " "
            if seconds == 1:
                out += self.translate("second")
            else:
                out += self.translate("seconds")
    else:
        # M:SS, MM:SS, H:MM:SS, Dd H:MM:SS format
        out = ""
        if days > 0:
            out = str(days) + "d "
        if hours > 0 or days > 0:
            out += str(hours) + ":"
        if minutes < 10 and (hours > 0 or days > 0):
            out += "0"
        out += str(minutes)+":"
        if seconds < 10:
            out += "0"
        out += str(seconds)

    return out
