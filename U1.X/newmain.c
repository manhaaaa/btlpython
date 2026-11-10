/*
 * File:   newmain.c
 * Target: PIC16F877A @ 20MHz (HS Oscillator)
 * System: Smart PIN Door Lock System with LCD 16x2 (LM016L)
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
 *     RD4 : LCD D4 (4-bit Data)
 *     RD5 : LCD D5 (4-bit Data)
 *     RD6 : LCD D6 (4-bit Data)
 *     RD7 : LCD D7 (4-bit Data)
 *   PORTA:
 *     RA0 : Close-door push button (Input, active LOW, external 10k pull-up)
 *   PORTC:
 *     RC0 : LCD RS (Register Select: 0=Command, 1=Data)
 *     RC1 : LCD EN (Enable Pulse)
 *     RC6 : TX (Output -> COMPIM TXD Pin 3, 9600 baud, 8N1)
 *     RC7 : RX (Input  -> COMPIM RXD Pin 2, 9600 baud, 8N1)
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

// LCD 16x2 Pin Definitions
#define LCD_RS PORTCbits.RC0
#define LCD_EN PORTCbits.RC1

// Precise millisecond delay using safe __delay_ms(1) loop
void Delay_Ms(unsigned int ms) {
    while(ms--) {
        __delay_ms(1);
    }
}

// ==========================================
// LCD 16x2 (LM016L) 4-BIT DRIVER ROUTINES
// ==========================================

void LCD_Pulse_Enable(void) {
    LCD_EN = 1;
    __delay_us(5);
    LCD_EN = 0;
    __delay_us(50);
}

void LCD_Send_Nibble(unsigned char nibble) {
    // Preserve RD0..RD3 (LEDs, Relay, Buzzer) and update RD4..RD7 with LCD nibble
    PORTD = (PORTD & 0x0F) | (nibble & 0xF0);
    LCD_Pulse_Enable();
}

void LCD_Command(unsigned char cmd) {
    LCD_RS = 0;
    LCD_Send_Nibble(cmd);                          // High nibble
    LCD_Send_Nibble((unsigned char)(cmd << 4));   // Low nibble
    __delay_ms(2);
}

void LCD_Char(char data) {
    LCD_RS = 1;
    LCD_Send_Nibble((unsigned char)data);         // High nibble
    LCD_Send_Nibble((unsigned char)(data << 4));  // Low nibble
    __delay_us(50);
}

void LCD_String(const char *str) {
    while(*str) {
        LCD_Char(*str++);
    }
}

void LCD_SetCursor(unsigned char row, unsigned char col) {
    unsigned char address = (row == 1) ? (0x80 + col) : (0xC0 + col);
    LCD_Command(address);
}

void LCD_Clear(void) {
    LCD_Command(0x01);
    __delay_ms(2);
}

void LCD_Init(void) {
    TRISCbits.TRISC0 = 0; // RC0 = Output (RS)
    TRISCbits.TRISC1 = 0; // RC1 = Output (EN)
    TRISD = 0x00;        // All PORTD Outputs

    LCD_RS = 0;
    LCD_EN = 0;
    __delay_ms(25);      // Power-up wait (> 15ms)

    // 4-bit initialization sequence
    LCD_Send_Nibble(0x30);
    __delay_ms(5);
    LCD_Send_Nibble(0x30);
    __delay_us(150);
    LCD_Send_Nibble(0x30);
    __delay_us(150);
    LCD_Send_Nibble(0x20); // Switch to 4-bit
    __delay_us(150);

    LCD_Command(0x28); // 4-bit mode, 2 lines, 5x8 font
    LCD_Command(0x0C); // Display ON, Cursor OFF
    LCD_Command(0x06); // Cursor increment, no display shift
    LCD_Clear();
}

void LCD_Display_Idle_Screen(unsigned char count) {
    LCD_SetCursor(1, 0);
    LCD_String("CUA DANG DONG   ");
    LCD_SetCursor(2, 0);
    LCD_String("Nhap PIN: ");
    for(unsigned char i = 0; i < 4; i++) {
        if(i < count) {
            LCD_Char('*');
        } else {
            LCD_Char('_');
        }
    }
    LCD_String("  ");
}

// ==========================================
// UART COMMUNICATION ROUTINES
// ==========================================

// Forward declarations
void UART_Send(char data);
void UART_Send_String(const char *str);
void UART_Check_Ping(void);

// UART Peripheral Initialization (9600 baud @ 20MHz, 8N1)
void UART_Init(void) {
    TRISCbits.TRISC6 = 1; // RC6 = TX (Datasheet recommendation; USART overrides)
    TRISCbits.TRISC7 = 1; // RC7 = RX (Input)
    SPBRG = 129;          // 9600 baud @ 20MHz with BRGH=1 (+0.16% error)
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

// Send string over UART
void UART_Send_String(const char *str) {
    while(*str) {
        UART_Send(*str++);
    }
    while(!TXSTAbits.TRMT); // Wait until last bit is transmitted
}

// Transmit 4-digit PIN followed by newline: <PIN4>\n
void UART_Send_PIN(const char *pin) {
    for(unsigned char i = 0; i < 4; i++) {
        UART_Send(pin[i]);
    }
    UART_Send('\n');
    while(!TXSTAbits.TRMT); // Wait until last bit is transmitted
}

// Check for active ping/poll character from Python ('?') and answer immediately ('!\n')
// Also recovers from OERR / FERR during idle loop so receiver never freezes
void UART_Check_Ping(void) {
    if(RCSTAbits.OERR) {
        RCSTAbits.CREN = 0;
        RCSTAbits.CREN = 1;
    }
    if(PIR1bits.RCIF) {
        if(RCSTAbits.FERR) {
            volatile char dummy = RCREG;
            (void)dummy;
            return;
        }
        char c = RCREG;
        if(c == '?') {
            UART_Send('!');
            UART_Send('\n');
            while(!TXSTAbits.TRMT);
        }
    }
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

// Poll RCIF with 5.0-second timeout; robust OERR and FERR recovery
// Returns 1 on success ('1', '0', or 'L' placed in *out_char), 0 on timeout
unsigned char UART_Receive_Timeout(char *out_char) {
    unsigned int timer_ms = 0;
    while(timer_ms < 5000) {
        if(RCSTAbits.OERR) {
            RCSTAbits.CREN = 0;
            RCSTAbits.CREN = 1;
        }
        if(PIR1bits.RCIF) {
            if(RCSTAbits.FERR) {
                volatile char dummy = RCREG;
                (void)dummy;
            } else {
                char c = RCREG;
                if(c == '1' || c == '0' || c == 'L') {
                    *out_char = c;
                    return 1;
                }
            }
        }
        __delay_ms(1);
        timer_ms++;
    }
    return 0; // Timeout
}

// ==========================================
// KEYPAD MATRIX SCANNING ROUTINES
// ==========================================

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

// Wait for a debounced keypress and key release, while servicing UART ping in background
char Keypad_GetKey(void) {
    char key;
    while((key = Keypad_Scan()) == 0) {
        UART_Check_Ping();
    }
    __delay_ms(2);
    while(Keypad_Scan() != 0) {
        UART_Check_Ping();
    }
    __delay_ms(2);
    return key;
}

// ==========================================
// ACTUATOR AND FEEDBACK ACTIONS
// ==========================================

// Turn off all actuators (LEDs, Relay, Buzzer) without modifying LCD lines
void All_Actuators_Off(void) {
    PORTDbits.RD0 = 0;
    PORTDbits.RD1 = 0;
    PORTDbits.RD2 = 0;
    PORTDbits.RD3 = 0;
}

// Blink Red LED twice on timeout or UART error (150ms ON / 150ms OFF x2)
void Blink_Red_Twice(void) {
    All_Actuators_Off();
    LCD_SetCursor(1, 0);
    LCD_String("LOI KET NOI PC! ");
    LCD_SetCursor(2, 0);
    LCD_String("KHONG PHAN HOI  ");
    PORTDbits.RD1 = 1;
    Delay_Ms(150);
    PORTDbits.RD1 = 0;
    Delay_Ms(150);
    PORTDbits.RD1 = 1;
    Delay_Ms(150);
    PORTDbits.RD1 = 0;
    Delay_Ms(150);
}

// Close-door push button on RA0 (pin 2), active LOW with external 10k pull-up to +5V
#define BTN_CLOSE PORTAbits.RA0

// Actuator Action: Response '1' (Access Granted)
// Turn ON Green LED (RD0) and Relay (RD2) and keep the door OPEN until the
// close button (RA0) is pressed. UART ping is serviced while waiting so the
// Python bridge keeps seeing the PIC alive. Sends "CLOSED\n" when door closes.
void Action_Access_Granted(void) {
    All_Actuators_Off();
    LCD_SetCursor(1, 0);
    LCD_String(" CUA DANG MO!   ");
    LCD_SetCursor(2, 0);
    LCD_String("Nhan nut de dong");
    PORTDbits.RD0 = 1; // Green LED ON
    PORTDbits.RD2 = 1; // Relay ON (door open)

    // Wait for button press (debounced: must stay LOW for 20ms)
    while(1) {
        UART_Check_Ping();
        if(BTN_CLOSE == 0) {
            Delay_Ms(20);
            if(BTN_CLOSE == 0) break;
        }
    }
    // Wait for button release
    while(BTN_CLOSE == 0) {
        UART_Check_Ping();
    }
    Delay_Ms(20);

    // Close the door
    All_Actuators_Off();
    LCD_SetCursor(1, 0);
    LCD_String("  CUA DA DONG   ");
    LCD_SetCursor(2, 0);
    LCD_String("                ");
    UART_Send_String("CLOSED\n"); // Notify Python app
    Delay_Ms(1000);
}

// Actuator Action: Response '0' (Access Denied)
// Turn ON Red LED (RD1) and Buzzer (RD3) for 1.5 seconds, then OFF
void Action_Access_Denied(void) {
    All_Actuators_Off();
    LCD_SetCursor(1, 0);
    LCD_String("  SAI MA PIN!   ");
    LCD_SetCursor(2, 0);
    LCD_String("VUI LONG THU LAI");
    PORTDbits.RD1 = 1; // Red LED ON
    PORTDbits.RD3 = 1; // Buzzer ON
    Delay_Ms(1500);    // Hold 1.5s (blocking, keypad ignored)
    All_Actuators_Off();
}

// Actuator Action: Response 'L' (System Locked Out)
// Blink Red LED (RD1) and Buzzer (RD3) chirp 3 times (200ms ON / 200ms OFF x3)
void Action_System_Locked(void) {
    All_Actuators_Off();
    LCD_SetCursor(1, 0);
    LCD_String("CANH BAO: KHOA! ");
    LCD_SetCursor(2, 0);
    LCD_String("KHOA TAM 30 GIAY");
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
// - Updates LCD 16x2 display with masked '*' characters.
// - Blinks Green LED (35ms) on valid digit entry.
// - Ignores extra digits once 4 digits have been entered.
// - '*' key resets buffer and input state (blinks Red LED 60ms).
// - '#' key submits ONLY when exactly 4 digits have been entered.
void Enter_PIN(char *pin) {
    unsigned char count = 0;
    char key;

    LCD_Display_Idle_Screen(count);

    while(1) {
        key = Keypad_GetKey();

        if(key >= '0' && key <= '9') {
            if(count < 4) {
                pin[count] = key;
                count++;
                LCD_Display_Idle_Screen(count);

                // Visual feedback: brief Green LED blink (35ms)
                PORTDbits.RD0 = 1;
                Delay_Ms(35);
                PORTDbits.RD0 = 0;
            }
        }
        else if(key == '*') {
            // Reset buffer and state
            count = 0;
            pin[0] = '\0';
            LCD_Display_Idle_Screen(count);

            // Visual feedback: brief Red LED blink (60ms)
            PORTDbits.RD1 = 1;
            Delay_Ms(60);
            PORTDbits.RD1 = 0;
        }
        else if(key == '#') {
            // Only submit if exactly 4 digits entered
            if(count == 4) {
                pin[4] = '\0';
                LCD_SetCursor(2, 0);
                LCD_String("Dang kiem tra...");
                return;
            }
        }
    }
}

void main(void) {
    char pin[5];
    char response;

    // Digital I/O Configuration (Disable Analog inputs)
    ADCON1 = 0x06;

    // RA0 = Input (close-door push button, external pull-up)
    TRISAbits.TRISA0 = 1;

    // Enable internal weak pull-ups on PORTB
    OPTION_REGbits.nRBPU = 0;

    // PORTB: RB0..RB2 Outputs (Cols), RB4..RB7 Inputs (Rows)
    TRISB = 0xF0;
    PORTB = 0xFF;

    // PORTD: RD0..RD3 Actuators, RD4..RD7 LCD Data
    TRISD = 0x00;
    PORTD = 0x00;

    // Initialize LCD 16x2 in 4-bit mode
    LCD_Init();

    // Initialize UART at 9600 baud, 8N1
    UART_Init();

    // Startup announcement: notify Python bridge that PIC firmware is ready
    UART_Send_String("READY\n");

    while(1) {
        All_Actuators_Off();

        // Step 1: Wait for 4-digit PIN input and '#' submit
        Enter_PIN(pin);

        // Step 2: Clear any stale UART receiver data/errors before transmitting
        UART_Flush();

        // Step 3: Transmit <PIN4>\n over UART to PC (COMPIM)
        UART_Send_PIN(pin);

        // Step 4: Wait for PC response with 5.0s timeout and OERR/FERR recovery
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
            // Timeout (5.0s) or UART framing/overrun error
            Blink_Red_Twice();
        }

        // Step 6: Ensure all actuators OFF and wait until keypad is released
        All_Actuators_Off();
        while(Keypad_Scan() != 0); // Ignore any key held during blocking action
        Delay_Ms(20);
    }
}
