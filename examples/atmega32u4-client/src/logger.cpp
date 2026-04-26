#include <logger.h>

void Logger::initLog() {
    Serial1.begin(115200);
    delay(100);

    for (uint8_t f = 0; f < FIELD_COUNT; f++) {
        queues[f].readIndex = 0;
        queues[f].writeIndex = 0;
        queues[f].queueID = f;
        for (uint8_t s = 0; s < SLOTS_PER_FIELD; s++) {
            queues[f].slots[s] = "";
        }
    }
}

void Logger::log(LOGED_FIELDS field, float value) {
    String msg = String(value, 4);
    msg += ':';
    msg += millis();
    queue(field, msg);
}

void Logger::log(LOGED_FIELDS field, int value) {
    String msg = String(value);
    msg += ':';
    msg += millis();
    queue(field, msg);
}

void Logger::queue(LOGED_FIELDS field, const String& message) {
    FieldQueue& queue = queues[field];

    queue.slots[queue.writeIndex] = message; 

    uint8_t nextReadIndex = (queue.readIndex + 1) % SLOTS_PER_FIELD;
    if (queue.writeIndex == queue.readIndex && queue.slots[nextReadIndex] != "") 
        queue.readIndex = nextReadIndex;
        
    queue.writeIndex = (queue.writeIndex + 1) % SLOTS_PER_FIELD;
}

void Logger::update() {
    static uint8_t nextQueueToSend = 0;
    uint8_t sentMessage = 0;

    // Send 1 message
    while (sentMessage < FIELD_COUNT) {
        sentMessage += 1;
        FieldQueue& queue = queues[nextQueueToSend];

        if (queue.slots[queue.readIndex] != "") {
            // Send data to esp
            Serial1.print(nextQueueToSend);
            Serial1.print(':');
            Serial1.println(queue.slots[queue.readIndex]);

            // Serial.print(nextQueueToSend);
            // Serial.print(':');
            // Serial.println(queue.slots[queue.readIndex]);

            // set queue to be empty and increses queue index
            queue.slots[queue.readIndex] = "";
            queue.readIndex = (queue.readIndex + 1) % SLOTS_PER_FIELD;

            sentMessage = FIELD_COUNT;
        }

        nextQueueToSend = (nextQueueToSend + 1) % FIELD_COUNT;
    }

    // Check for new Message
    String message;
    if (checkReceived(message)) {
        Serial.print("Rec'd:\t");
        Serial.print(message);
    }
}

bool Logger::checkReceived(String& SerialString) 
{
    SerialString = "";

    while(Serial1.available())
    {
        char c = Serial1.read();
        SerialString += c;

        if(c == '\n')
        {
            return true;
        }
    }

    return false;
}