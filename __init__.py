from mycroft import MycroftSkill, intent_file_handler


class VideoRecord(MycroftSkill):
    def __init__(self):
        MycroftSkill.__init__(self)

    @intent_file_handler('record.video.intent')
    def handle_record_video(self, message):
        self.speak_dialog('record.video')


def create_skill():
    return VideoRecord()

