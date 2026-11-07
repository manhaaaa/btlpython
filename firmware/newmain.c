/*
 * File:   newmain.c
 * Target: PIC16F877A @ 20MHz (HS Oscillator)
 * System: Smart PIN Door Lock System (Milestone 3 / R3)
 * Compiler: Microchip MPLAB XC8 v3.10
 *
 * Pin Connections:
 *   PORTB:
 *     RB0..RB2 : Keypad Matrix Columns (Outputs)
 *     RB4..RB7 : Keypad Matrix Rows (Inputs with weak pull-ups enabled)
 *   PORTD:
 *     RD0 : Green LED (Active High, Access Granted / Key Feedback)
 *     RD1 : Red LED (Active High, Access Denied / Error / Reset Feedback)
 *     RD2 : Relay RL1 for Door Motor (Active High, Access Granted)
 *     RD3 : Buzzer BUZ1 (Active High, Access Denied / Lockout Alarm)
 *   PORTC:
 *     RC6 : TX (Output -> COMPIM RXD, 9600 baud, 8N1)
 *     RC7 : RX (Input  -> COMPIM TXD, 9600 baud, 8N1)
 */

#include <xc.h>
#include <string.h>

#define _XTAL_FREQ 20000000

// Configuration Bits
#pragma config FOSC = HS        // High Speed Crystal (20MHz)
#pragma config WDTE = OFF       // Watchdog Timer disabled
#pragma config PWRTE = OFF      // Power-up Timer disabled
#pragma config BOREN = ON       // Brown-out Reset enabled
#pragma config LVP = OFF        // Low Voltage Programming disabled
#pragma config CPD = OFF        // Data EEPROM Code Protection disabled
#pragma config WRT = OFF        // Flash Program Memory Write disabled
#pragma config CP = OFF         // Flash Code Protection disabled

// Keypad 3x4 Matrix Mapping: [Rows RB4..RB7][Columns RB0..RB2]
static const char keypad[4][3] = {
    {'1', '2', '3'}, // Row A: RB4
    {'4', '5', '6'}, // Row B: RB5
    {'7', '8', '9'}, // Row C: RB6
    {'*', '0', '#'}  // Row D: RB7
};

// Precise millisecond delay using safe __delay_ms(1) loop
void Delay_Ms(unsigned int ms) {
    while(ms--) {
        __delay_ms(1);
    }
}

// UART Peripheral Initialization (9600 baud @ 20MHz, 8N1)
void UART_Init(void) {
    TRISCbits.TRISC6 = 0; // RC6 = TX (Output)
    TRISCbits.TRISC7 = 1; // RC7 = RX (Input)
    SPBRG = 129;          // 9600 baud @ 20MHz with BRGH=1
    TXSTAbits.BRGH = 1;   // High speed baud rate
    TXSTAbits.SYNC = 0;   // Asynchronous mode
    RCSTAbits.SPEN = 1;   // Serial Port Enable
    TXSTAbits.TXEN = 1;   // Transmit Enable
    RCSTAbits.CREN = 1;   // Continuous Receive Enable
}

// Send single character over UART
void UART_Send(char data) {
    while(!PIR1bits.TXIF);
    TXREG = data;
}

// Transmit 4-digit PIN followed by newline: <PIN4>\n
void UART_Send_PIN(const char *pin) {
    for(unsigned char i = 0; i < 4; i++) {
        UART_Send(pin[i]);
    }
    UART_Send('\n');
    while(!TXSTAbits.TRMT); // Wait until last bit is transmitted
}

// Flush receive buffer and clear overrun errors
void UART_Flush(void) {
    if(RCSTAbits.OERR) {
        RCSTAbits.CREN = 0;
        RCSTAbits.CREN = 1;
    }
    while(PIR1bits.RCIF) {
        volatile char dummy = RCREG;
        (void)dummy;
    }
}

// Poll RCIF with 3.0-second timeout; clear OERR on overrun
// Returns 1 on success (char placed in *out_char), 0 on timeout or error
unsigned char UART_Receive_Timeout(char *out_char) {
    unsigned int timer_ms = 0;
    while(timer_ms < 3000) {
        if(RCSTAbits.OERR) {
            RCSTAbits.CREN = 0;
            RCSTAbits.CREN = 1;
            return 0; // Overrun error detected
        }
        if(PIR1bits.RCIF) {
            *out_char = RCREG;
            return 1; // Character received
        }
        __delay_ms(1);
        timer_ms++;
    }
    return 0; // 3.0s Timeout
}

// Keypad row scanning across columns RB0..RB2
char Keypad_Scan(void) {
    unsigned char col;
    for(col = 0; col < 3; col++) {
        // Drive active column LOW, others HIGH
        PORTB = 0xFF & ~(1 << col);
        __delay_us(100);

        if(!PORTBbits.RB4) return keypad[0][col];
        if(!PORTBbits.RB5) return keypad[1][col];
        if(!PORTBbits.RB6) return keypad[2][col];
        if(!PORTBbits.RB7) return keypad[3][col];
    }
    PORTB = 0xFF;
    return 0;
}

// Wait for a debounced keypress and key release
char Keypad_GetKey(void) {
    char key;
    while((key = Keypad_Scan()) == 0);
    __delay_ms(2);
    while(Keypad_Scan() != 0);
    __delay_ms(2);
    return key;
}

// Turn off all actuators (LEDs, Relay, Buzzer)
void All_Actuators_Off(void) {
    PORTDbits.RD0 = 0;
    PORTDbits.RD1 = 0;
    PORTDbits.RD2 = 0;
    PORTDbits.RD3 = 0;
}

// Blink Red LED twice on timeout or UART error (150ms ON / 150ms OFF x2)
void Blink_Red_Twice(void) {
    All_Actuators_Off();
    PORTDbits.RD1 = 1;
    Delay_Ms(150);
    PORTDbits.RD1 = 0;
    Delay_Ms(150);
    PORTDbits.RD1 = 1;
    Delay_Ms(150);
    PORTDbits.RD1 = 0;
    Delay_Ms(150);
}

// Actuator Action: Response '1' (Access Granted)
// Turn ON Green LED (RD0) and Relay (RD2) for 3.0 seconds, then OFF
void Action_Access_Granted(void) {
    All_Actuators_Off();
    PORTDbits.RD0 = 1; // Green LED ON
    PORTDbits.RD2 = 1; // Relay ON (Motor spins)
    Delay_Ms(3000);    // Hold 3.0s (blocking, keypad ignored)
    All_Actuators_Off();
}

// Actuator Action: Response '0' (Access Denied)
// Turn ON Red LED (RD1) and Buzzer (RD3) for 1.5 seconds, then OFF
void Action_Access_Denied(void) {
    All_Actuators_Off();
    PORTDbits.RD1 = 1; // Red LED ON
    PORTDbits.RD3 = 1; // Buzzer ON
    Delay_Ms(1500);    // Hold 1.5s (blocking, keypad ignored)
    All_Actuators_Off();
}

// Actuator Action: Response 'L' (System Locked Out)
// Blink Red LED (RD1) and Buzzer (RD3) chirp 3 times (200ms ON / 200ms OFF x3)
void Action_System_Locked(void) {
    All_Actuators_Off();
    for(unsigned char i = 0; i < 3; i++) {
        PORTDbits.RD1 = 1; // Red LED ON
        PORTDbits.RD3 = 1; // Buzzer ON
        Delay_Ms(200);
        PORTDbits.RD1 = 0; // Red LED OFF
        PORTDbits.RD3 = 0; // Buzzer OFF
        Delay_Ms(200);
    }
    All_Actuators_Off();
}

// Keypad PIN Entry State Machine:
// - Accumulates up to 4 digits into pin buffer.
// - Blinks Green LED (35ms) on valid digit entry.
// - Ignores extra digits once 4 digits have been entered.
// - '*' key resets buffer and input state (blinks Red LED 60ms).
// - '#' key submits ONLY when exactly 4 digits have been entered.
void Enter_PIN(char *pin) {
    unsigned char count = 0;
    char key;

    while(1) {
        key = Keypad_GetKey();

        if(key >= '0' && key <= '9') {
            if(count < 4) {
                pin[count] = key;
                count++;

                // Visual feedback: brief Green LED blink (35ms)
                PORTDbits.RD0 = 1;
                Delay_Ms(35);
                PORTDbits.RD0 = 0;
            }
            // Extra digits ignored if count == 4
        }
        else if(key == '*') {
            // Reset buffer and state
            count = 0;
            pin[0] = '\0';

            // Visual feedback: brief Red LED blink (60ms)
            PORTDbits.RD1 = 1;
            Delay_Ms(60);
            PORTDbits.RD1 = 0;
        }
        else if(key == '#') {
            // Only submit if exactly 4 digits entered
            if(count == 4) {
                pin[4] = '\0';
                return;
            }
            // If count < 4, '#' key is ignored
        }
    }
}

void main(void) {
    char pin[5];
    char response;

    // Digital I/O Configuration (Disable Analog inputs)
    ADCON1 = 0x06;

    // Enable internal weak pull-ups on PORTB
    OPTION_REGbits.nRBPU = 0;

    // PORTB: RB0..RB2 Outputs (Cols), RB4..RB7 Inputs (Rows)
    TRISB = 0xF0;
    PORTB = 0xFF;

    // PORTD: RD0 (Green LED), RD1 (Red LED), RD2 (Relay), RD3 (Buzzer)
    TRISD = 0x00;
    PORTD = 0x00;

    // Initialize UART at 9600 baud, 8N1
    UART_Init();

    while(1) {
        All_Actuators_Off();

        // Step 1: Wait for 4-digit PIN input and '#' submit
        Enter_PIN(pin);

        // Step 2: Clear any stale UART receiver data/errors before transmitting
        UART_Flush();

        // Step 3: Transmit <PIN4>\n over UART to PC (COMPIM)
        UART_Send_PIN(pin);

        // Step 4: Wait for PC response with 3.0s timeout and OERR recovery
        if(UART_Receive_Timeout(&response)) {
            // Step 5: Handle response character
            if(response == '1') {
                Action_Access_Granted();
            }
            else if(response == '0') {
                Action_Access_Denied();
            }
            else if(response == 'L') {
                Action_System_Locked();
            }
            else {
                // Unexpected response character -> Treat as error
                Blink_Red_Twice();
            }
        }
        else {
            // Timeout (3.0s) or UART framing/overrun error
            Blink_Red_Twice();
        }

        // Step 6: Ensure all actuators OFF and wait until keypad is released
        All_Actuators_Off();
        while(Keypad_Scan() != 0); // Ignore any key held during blocking action
        Delay_Ms(20);
    }
}
