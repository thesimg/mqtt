#include <Arduino.h>

class Logger {
public:

    enum LOGED_FIELDS {
        HEADING,
        PITCH,
        ROLL,
        ENCODER_L,
        ENCODER_R,
        POS_X,
        POS_Y,
        STATE,
        FIELD_COUNT
    };
    
    void initLog();
    void log(LOGED_FIELDS field, float value);
    void log(LOGED_FIELDS field, int value);
    void update();

    private:
    static const uint8_t SLOTS_PER_FIELD = 3;
    
    struct FieldQueue {
        String slots[SLOTS_PER_FIELD];
        uint8_t writeIndex;
        uint8_t readIndex;
        uint8_t queueID;
    };
    
    FieldQueue queues[FIELD_COUNT];
    
    void queue(LOGED_FIELDS field, const String& message);

    bool checkReceived(String&);
};
