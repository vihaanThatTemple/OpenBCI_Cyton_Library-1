#define BLOCK_5MIN    16890 
#define BLOCK_15MIN  (BLOCK_5MIN*3)    
#define BLOCK_30MIN  (BLOCK_15MIN*2)   
#define BLOCK_1HR    (BLOCK_30MIN*2)  
#define BLOCK_2HR    (BLOCK_1HR*2)    
#define BLOCK_4HR    (BLOCK_1HR*4)    
#define BLOCK_12HR   (BLOCK_1HR*12)  
#define BLOCK_24HR   (BLOCK_1HR*24) 

#define OVER_DIM      20 // make room for up to 20 write-time overruns
#define ERROR_LED     false
#define OK_LED        true

char    fileSize = '0';  // SD file size indicator
int blockCounter =  0 ;


uint32_t BLOCK_COUNT;
SdFile openfile;  // want to put this before setup...
Sd2Card card(&board.spi,SD_SS);// SPI needs to be init'd before here
SdVolume volume;
SdFile root;
uint8_t* pCache;      // array that points to the block buffer on SD card
uint32_t MICROS_PER_BLOCK = 2000; // block write longer than this will get flaged
uint32_t bgnBlock, endBlock; // file extent bookends
int byteCounter = 0;    // used to hold position in cache
//int blockCounter;       // count up to BLOCK_COUNT with this
boolean openvol;
boolean cardInit = false;
boolean fileIsOpen = false;
static bool sdFullFired = false; // P2-4: one-shot latch so SD_FULL tokens don't spray
static uint32_t cachedTotalBlocks = 0; // P2-6: populated on first successful card.init()

struct {
  uint32_t block;   // holds block number that over-ran
  uint32_t micro;  // holds the length of this of over-run
} over[OVER_DIM];

uint32_t overruns;      // count the number of overruns
uint32_t maxWriteTime;  // keep track of longest write time
uint32_t minWriteTime;  // and shortest write time
uint32_t t;        // used to measure total file write time
uint8_t ERROR_BLINKS = 3;
uint8_t OK_BLINKS    = 3;


byte fileTens, fileOnes;  // enumerate succesive files on card and store number in EEPROM
char currentFileName[] = "OBCI_00.TXT"; // file name will enumerate in hex 00 - FF
prog_char samplingFreq[] PROGMEM = {"\n%SamplingFreq:\n"};  // 16
prog_char elapsedTime[] PROGMEM = {"%Total time mS:\n"};  // 17
prog_char minTime[] PROGMEM = {  "%min Write time uS:\n"};  // 20
prog_char maxTime[] PROGMEM = {  "%max Write time uS:\n"};  // 20
prog_char overNum[] PROGMEM = {  "%Over:\n"};               //  7
prog_char blockTime[] PROGMEM = {  "%block, uS\n"};         // 11    74 chars + 2 32(16) + 2 16(8) = 98 + (n 32x2) up to 24 overruns...
prog_char stopStamp[] PROGMEM = {  "%STOP AT\n"};      // used to stamp SD record when stopped by PC
prog_char startStamp[] PROGMEM = {  "%START AT\n"};    // used to stamp SD record when started by PC



// P2-5: on every early-close path we need the FAT directory entry to reflect the
// actual byte count, not the pre-allocated BLOCK_COUNT*512. On SdFat forks that
// expose truncate(), use it; otherwise fall back to remove() and warn host.
// The Concern-5 note in the debate brief flags this build-time check: if neither
// truncate nor remove-on-open-file is available, the offline parser is expected
// to detect EOF via the tail-canary magic instead of trusting file size.
static void sdTruncateOrReportIncomplete(uint32_t blocksWritten) {
  const uint32_t realBytes = blocksWritten * 512UL;
#if defined(SdFat_HAS_TRUNCATE)
  if (!openfile.truncate(realBytes)) {
    if (!board.streaming) Serial0.print("$SDERR:FILE_INCOMPLETE$$$");
  }
#else
  // Best-effort: leave the file on-card; emit the token so the host flags it.
  (void)realBytes;
  if (!board.streaming) Serial0.print("$SDERR:FILE_INCOMPLETE$$$");
#endif
}

// P2-2 / Change 3: read ADS1299 Device ID WITHOUT clobbering board.regData[].
// Issues SDATAC first (idempotent; safe if already in SDATAC), waits 10 us,
// then a manual RREG sequence (0x20 | addr, 0x00, read). Returns 0xFF on
// unrecoverable error. Valid ID is 0x3E (ADS1299 8-channel variant).
static byte diagReadAdsId(uint8_t targetSS) {
  // SDATAC: ADS stops continuous-data framing. Idempotent per SBAS499C §9.5.2.2.
  board.SDATAC(targetSS);
  board.channelDataAvailable = false; // B1: clear stale DRDY flag after SDATAC
  delayMicroseconds(10);
  board.csLow(targetSS);       // MODE1 @ 4 MHz per csLow switch in library
  board.xfer(0x20 | 0x00);     // RREG op for register 0x00 (ID)
  board.xfer(0x00);             // "read 1 register" (N-1 = 0)
  byte id = board.xfer(0x00);  // shift in the ID byte
  board.csHigh(targetSS);
  return id;
}

bool LED_SD_Status_Indication(uint8_t blinks_num, uint8_t blink_period_num, bool ok_indication){
  
  for(uint8_t i=0; i<blinks_num; i++){
     digitalWrite(OPENBCI_PIN_LED, LOW);
     delay(blink_period_num);
     digitalWrite(OPENBCI_PIN_LED, HIGH);
     delay(blink_period_num);
  }
  
  if(ok_indication){
    digitalWrite(OPENBCI_PIN_LED,HIGH);
    return true;
  }else {
    digitalWrite(OPENBCI_PIN_LED,LOW);
    return false;
  }
  
}



char sdProcessChar(char character) {
  
    switch (character) {
        case 'A': // 5min
        case 'S': // 15min
        case 'F': // 30min
        case 'G': // 1hr
        case 'H': // 2hr
        case 'J': // 4hr
        case 'K': // 12hr
        case 'L': // 24hr
        case 'a': // 512 blocks
             
            fileSize = character;
            SDfileOpen = setupSDcard(character);
            break;
            
        case 'j': // close the file, if it's open
            if(SDfileOpen){

                SDfileOpen = closeSDfile();
            }
            if(board.streaming)board.streamStop(); // Stop streamming 
            break;
            
        case 's':
            if(SDfileOpen) {
              
                stampSD(ACTIVATE);
            }
            break;
            
        case 'b':
            if(SDfileOpen) {
                stampSD(DEACTIVATE);
            }
            break;

        default:
            break;
        
    }

    return character;

}


// P2-8 + P2-9: single-frame diag emission.
// stage = 0 → early (before card.init): free_blocks=NA file=NA
// stage = 1 → success: all fields resolved.
static void emitSdDiag(uint8_t stage) {
  if (board.streaming) return; // do not interleave with live sample frames
  byte adsId = diagReadAdsId(BOARD_ADS);
  byte daisyId = 0xFF;
  bool daisyValid = false;
  if (board.daisyPresent) {
    daisyId = diagReadAdsId(DAISY_ADS);
    daisyValid = true;
  }
  const uint32_t freeBlocks =
      (stage == 1 && cachedTotalBlocks > BLOCK_COUNT)
          ? (cachedTotalBlocks - BLOCK_COUNT)
          : 0;

  Serial0.print("%SD_DIAG fw=v3.1.5-p0 ads_id=0x");
  if (adsId < 0x10) Serial0.print('0');
  Serial0.print(adsId, HEX);
  Serial0.print(" daisy_id=");
  if (daisyValid) {
    Serial0.print("0x");
    if (daisyId < 0x10) Serial0.print('0');
    Serial0.print(daisyId, HEX);
  } else {
    Serial0.print("NA");
  }
  Serial0.print(" rtc=");   Serial0.print(millis());
  Serial0.print(" sps=");   Serial0.print(board.getSampleRate());
  if (stage == 1) {
    Serial0.print(" free_blocks="); Serial0.print(freeBlocks);
    Serial0.print(" file="); Serial0.print(currentFileName);
  } else {
    Serial0.print(" free_blocks=NA file=NA");
  }
  Serial0.print("$$$");
}

boolean setupSDcard(char limit){
  // P2-1: clear stale extent cursors so an early-return cannot feed garbage to erase/writeStart.
  bgnBlock = 0;
  endBlock = 0;

  if(!cardInit){
      if(!card.init(SPI_FULL_SPEED, SD_SS)) {
        if(!board.streaming) {
          Serial0.println("initialization failed. Things to check:");
          Serial0.println("* is a card is inserted?");
        }
        emitSdDiag(0);
        return fileIsOpen; // P2-1 + P2-11: surface diag even on card-absent.
      } else {
        if(!board.streaming) {
          Serial0.println("Wiring is correct and a card is present.");
        }
        cardInit = true;
        if (cachedTotalBlocks == 0) {
          cachedTotalBlocks = card.cardSize(); // P2-6: one-shot; avoid CMD9 per arm.
        }
      }
      if (!volume.init(card)) { // Now we will try to open the 'volume'/'partition' - it should be FAT16 or FAT32
        if(!board.streaming) {
          Serial0.println("Could not find FAT16/FAT32 partition. Make sure you've formatted the card");
        }
        emitSdDiag(0);
        return fileIsOpen;
      }
   }


       
  // Change 4: size the reservation from actual channels × SPS × duration + 10% margin.
  // bytes_per_sample is the hex-ASCII volume emitted by writeDataToSDcard():
  //   1 header byte (2 nibbles + ',') = 3
  //   N channels × (5 nibbles + ',' or '\n') = N*6 + N (comma/newline)
  //   8-ch board: 3 + 8*7 = 59
  //   16-ch daisy: 3 + 16*7 = 115
  // Add 12 bytes/sample of worst-case aux/accel overhead to stay conservative.
  const uint32_t bytes_per_sample = board.daisyPresent ? (3 + 16*7 + 12) : (3 + 8*7 + 12);
  const uint32_t sps = (uint32_t)atoi(board.getSampleRate());
  uint32_t duration_s;
  switch(limit){
    case 'h': duration_s = 1;           break;
    case 'a': duration_s = 10;          break;
    case 'A': duration_s = 5UL*60;      break;
    case 'S': duration_s = 15UL*60;     break;
    case 'F': duration_s = 30UL*60;     break;
    case 'G': duration_s = 60UL*60;     break;
    case 'H': duration_s = 2UL*60*60;   break;
    case 'J': duration_s = 4UL*60*60;   break;
    case 'K': duration_s = 12UL*60*60;  break;
    case 'L': duration_s = 24UL*60*60;  break;
    default:
      if(!board.streaming) {
        Serial0.println("invalid BLOCK count");
      }
      emitSdDiag(0);
      return fileIsOpen;
  }
  // Defense 14: refuse if SPS parsing returned 0 (would produce BLOCK_COUNT=0 and instant SD_FULL).
  if (sps == 0) {
    if(!board.streaming) {
      Serial0.print("$SDERR:INVALID_SPS$$$");
    }
    emitSdDiag(0);
    return fileIsOpen;
  }
  const uint64_t raw_bytes  = (uint64_t)bytes_per_sample * sps * duration_s;
  const uint64_t raw_blocks = (raw_bytes + 511ULL) / 512ULL;        // ceil
  const uint64_t padded     = (raw_blocks * 11ULL + 9ULL) / 10ULL;  // +10% margin (ceil)
  if (padded > 0xFFFFFFFFULL) {
    if(!board.streaming) {
      Serial0.println("duration exceeds uint32 block range");
    }
    emitSdDiag(0);
    return fileIsOpen;
  }
  BLOCK_COUNT = (uint32_t)padded;
  sdFullFired = false; // P2-4: reset one-shot at arm time

 
  incrementFileCounter();
  openvol = root.openRoot(volume);
  openfile.remove(root, currentFileName); // if the file is over-writing, let it!

  if (!openfile.createContiguous(root, currentFileName, BLOCK_COUNT*512UL)) {
    if(!board.streaming) {
      Serial0.print("createfdContiguous fail");
      LED_SD_Status_Indication(ERROR_BLINKS, 500, ERROR_LED);
    }
    cardInit = false;
    emitSdDiag(0);
    return fileIsOpen; // P2-1
  }//else{Serial0.print("got contiguous file...");delay(1);}
  // get the location of the file's blocks
  if (!openfile.contiguousRange(&bgnBlock, &endBlock)) {
    if(!board.streaming) {
      Serial0.print("get contiguousRange fail");
      LED_SD_Status_Indication(ERROR_BLINKS, 500, ERROR_LED);
    }
    cardInit = false;
    emitSdDiag(0);
    return fileIsOpen; // P2-1
  }//else{Serial0.print("got file range...");delay(1);}
  
  // grab the Cache
  pCache = (uint8_t*)volume.cacheClear();
  
  // tell card to setup for multiple block write with pre-erase
  if (!card.erase(bgnBlock, endBlock)){
    if(!board.streaming) {
      Serial0.println("erase block fail");
      LED_SD_Status_Indication(ERROR_BLINKS, 500, ERROR_LED);
    }
    cardInit = false;
    emitSdDiag(0);
    return fileIsOpen; // P2-1
  }//else{Serial0.print("erased...");delay(1);}
 
  if (!card.writeStart(bgnBlock, BLOCK_COUNT)){
    if(!board.streaming) {
      Serial0.println("writeStart fail");
      LED_SD_Status_Indication(ERROR_BLINKS, 500, ERROR_LED);
    }
    cardInit = false;
    board.csHigh(SD_SS);
    emitSdDiag(0);
    return fileIsOpen;
  }

  // Change 1: offset-0 canary. SD CS is LOW, CMD25 just opened.
  // If canary writeData fails, we're in a partially-constructed CMD25 state;
  // clean tear-down is writeStop -> csHigh -> truncate helper -> openfile.close.
  memset(pCache, 0x00, 512);
  {
    const char kMagic[16] = {'O','B','C','I','_','C','A','N','A','R','Y','_','V','0','1', 0x01};
    memcpy(pCache + 0, kMagic, 16);
  }
  uint32_t canaryMillis = millis();
  pCache[16] = (canaryMillis      ) & 0xFF;
  pCache[17] = (canaryMillis >>  8) & 0xFF;
  pCache[18] = (canaryMillis >> 16) & 0xFF;
  pCache[19] = (canaryMillis >> 24) & 0xFF;
  pCache[20] = (uint8_t)board.curSampleRate;  // SPS enum
  pCache[21] = (uint8_t)board.daisyPresent;    // 0 or 1
  pCache[22] = (BLOCK_COUNT      ) & 0xFF;
  pCache[23] = (BLOCK_COUNT >>  8) & 0xFF;
  pCache[24] = (BLOCK_COUNT >> 16) & 0xFF;
  pCache[25] = (BLOCK_COUNT >> 24) & 0xFF;
  // 26..73: 8 channels x 6 bytes of channelSettings snapshot
  {
    uint16_t idx = 26;
    for (uint8_t ch = 0; ch < 8; ch++) {
      pCache[idx++] = board.channelSettings[ch][POWER_DOWN];
      pCache[idx++] = board.channelSettings[ch][GAIN_SET];
      pCache[idx++] = board.channelSettings[ch][INPUT_TYPE_SET];
      pCache[idx++] = board.channelSettings[ch][BIAS_SET];
      pCache[idx++] = board.channelSettings[ch][SRB2_SET];
      pCache[idx++] = board.channelSettings[ch][SRB1_SET];
    }
  }
  // Remainder stays 0x00 from memset.

  if (!card.writeData(pCache)) {
    // Canary failed -- tear CMD25 down cleanly. Don't write more.
    card.writeStop();
    board.csHigh(SD_SS);
    sdTruncateOrReportIncomplete(0); // P2-5: 0 real blocks, directory entry is a lie
    openfile.close();
    cardInit = false;
    fileIsOpen = false;
    if (!board.streaming) {
      Serial0.print("$SDERR:CANARY_FAIL$$$");
    }
    emitSdDiag(0);
    return fileIsOpen;
  }

  fileIsOpen = true;
  delay(1);
  board.csHigh(SD_SS);

  // Counters reflect that canary consumed one block already.
  overruns = 0;
  maxWriteTime = 0;
  minWriteTime = 65000;
  byteCounter = 0;
  blockCounter = 1; // canary = block 0 already written
  // P2-8: single merged diag+filename frame replaces the previous two-frame protocol.
  if (fileIsOpen) {
    LED_SD_Status_Indication(OK_BLINKS, 250, OK_LED);
  }
  emitSdDiag(1);
  return fileIsOpen;
}






boolean closeSDfile(){

  if(fileIsOpen){
    board.csLow(SD_SS);  // take spi
    card.writeStop();
    openfile.close();
    board.csHigh(SD_SS);  // release the spi
    fileIsOpen = false;
    if(!board.streaming){ // verbosity. this also gets insterted as footer in openFile
      Serial0.print("SamplingRate: ");Serial0.print(board.getSampleRate());Serial0.println("Hz"); //delay(10);
      Serial0.print("Total Elapsed Time: ");Serial0.print(t);Serial0.println(" mS");              //delay(10);
      Serial0.print("Max write time: "); Serial0.print(maxWriteTime); Serial0.println(" uS");     //delay(10);
      Serial0.print("Min write time: ");Serial0.print(minWriteTime); Serial0.println(" uS");      //delay(10);
      Serial0.print("Overruns: "); Serial0.print(overruns); Serial0.println(); //delay(10);
      if (overruns) {
        uint8_t n = overruns > OVER_DIM ? OVER_DIM : overruns;
        Serial0.println("fileBlock,micros");
        for (uint8_t i = 0; i < n; i++) {
          Serial0.print(over[i].block); Serial0.print(','); Serial0.println(over[i].micro);
        }
        
      }
      board.sendEOT();
    }


  }else{
    if(!board.streaming) {
      Serial0.println("No open file to close");
      board.sendEOT();
    }
    
  }
  
  // delay(100); // cool down
  return fileIsOpen;
}



void writeDataToSDcard(byte sampleNumber){
  boolean addComma = true;
  // convert 8 bit sampleCounter into HEX
  convertToHex(sampleNumber, 1, addComma);
  // convert 24 bit channelData into HEX
  for (int currentChannel = 0; currentChannel < 8; currentChannel++){
    convertToHex(board.boardChannelDataInt[currentChannel], 5, addComma);
    
    // If Daisy Is NOT Attached -> stop putting comma delimiter at 7th sample 
    if(board.daisyPresent == false){
      if(currentChannel == 6){
        addComma = false;
        if(addAuxToSD || addAccelToSD) { addComma = true; }  // format CSV
      }
    }
    
   } 

   // If Daisy Is Attached -> stop putting comma delimiter at 7th sample
  if(board.daisyPresent){
    for (int currentChannel = 0; currentChannel < 8; currentChannel++){
      convertToHex(board.daisyChannelDataInt[currentChannel], 5, addComma);
      if(currentChannel == 6){
        addComma = false;
        if(addAuxToSD || addAccelToSD) {addComma = true;}  // format CSV
      }
    }
    
  }

  

  if(addAuxToSD == true){
    // convert auxData into HEX
    for(int currentChannel = 0; currentChannel <  3; currentChannel++){
      convertToHex(board.auxData[currentChannel], 3, addComma);
      if(currentChannel == 1) addComma = false;
    }
    addAuxToSD = false;
  }// end of aux data log

  
  else if(addAccelToSD == true){  // if we have accelerometer data to log
    // convert 16 bit accelerometer data into HEX
    for (int currentChannel = 0; currentChannel < 3; currentChannel++){
      convertToHex(board.axisData[currentChannel], 3, addComma);
      if(currentChannel == 1) addComma = false;
    }
    addAccelToSD = false;  // reset addAccel
  }// end of accelerometer data log

   // add aux data logging...
}



void writeCache(){
    
    // Change 4 + P2-4: graceful stop on full reservation; one-shot so we don't spray.
    if (blockCounter >= BLOCK_COUNT) {
      if (!sdFullFired) {
        sdFullFired = true;
        if (!board.streaming) {
          Serial0.print("$SDERR:SD_FULL$$$");
        }
        SDfileOpen = closeSDfile();
        if (board.streaming) {
          board.streamStop(); // P2-4: also halt ADS so no more samples are dropped
        }
      }
      return;
    }
    
    uint32_t tw = micros();  // start block write timer
    board.csLow(SD_SS);  // take spi
    if(!card.writeData(pCache)) {
      if (!board.streaming) {
        Serial0.println("block write fail");
        board.sendEOT();
      }
    }   // write the block
    board.csHigh(SD_SS);  // release spi
    tw = micros() - tw;      // stop block write timer
    if (tw > maxWriteTime) maxWriteTime = tw;  // check for max write time
    if (tw < minWriteTime) minWriteTime = tw;  // check for min write time
    if (tw > MICROS_PER_BLOCK) {      // check for overrun
    if (overruns < OVER_DIM) {
        over[overruns].block = blockCounter;
        over[overruns].micro = tw;
      }
      overruns++;
    }

    byteCounter = 0; // reset 512 byte counter for next block
    blockCounter++;    // increment BLOCK counter
    
    if (blockCounter == BLOCK_COUNT - 2) {
      t = millis() - t;
      writeFooter(); // penultimate block = existing footer
    }

    if (blockCounter == BLOCK_COUNT - 1) {
      // P2-3: quiesce ADS BEFORE the final SD work so no DRDY edges fire
      // during tail-canary writeData + closeSDfile.
      if (board.streaming) {
        board.stopADS(); // issues SDATAC(BOTH_ADS)
      }
      writeTailCanary();
      blockCounter++; // advance past BLOCK_COUNT-1 so the equality below fires
    }

    if (blockCounter == BLOCK_COUNT) {
      SDfileOpen = closeSDfile();
      if (board.streaming) {
        board.streamStop(); // P2-3: finalize transport state after file is closed
      }
    }  // we did it!
    
}


void incrementFileCounter(){
  
  fileTens = EEPROM.read(0);
  fileOnes = EEPROM.read(1);
 
  // if it's the first time writing to EEPROM, seed the file number to '00'
  if(fileTens == 0xFF | fileOnes == 0xFF){
    fileTens = fileOnes = '0';
  }
  fileOnes++;   // increment the file name
  if (fileOnes == ':'){fileOnes = 'A';}
  if (fileOnes > 'F'){
    fileOnes = '0';         // hexify
    fileTens++;
    if(fileTens == ':'){fileTens = 'A';}
    if(fileTens > 'F'){fileTens = '0';fileOnes = '1';}
  }
  EEPROM.write(0,fileTens);     // store current file number in eeprom
  EEPROM.write(1,fileOnes);
  currentFileName[5] = fileTens;
  currentFileName[6] = fileOnes;
   //  // send corresponding file name to controlling program
   //  Serial0.print("Corresponding SD file ");Serial0.println(currentFileName);
}






void stampSD(boolean state){

  unsigned long time = millis();
  if(state){
    for(int i=0; i<10; i++){
      pCache[byteCounter] = pgm_read_byte_near(startStamp+i);
      byteCounter++;
      if(byteCounter == 512){
        writeCache();
      }
    }
  }
  else{
    for(int i=0; i<9; i++){
      pCache[byteCounter] = pgm_read_byte_near(stopStamp+i);
      byteCounter++;
      if(byteCounter == 512){
        writeCache();
      }
    }
  }
  convertToHex(time, 7, false);
}




void writeFooter(){
 
  for(int i=0; i<16; i++){
    pCache[byteCounter] = pgm_read_byte_near(samplingFreq+i);
    byteCounter++;
  }
  convertToHex(atoi(board.getSampleRate()), 4, false);
  
  for(int i=0; i<17; i++){
    pCache[byteCounter] = pgm_read_byte_near(elapsedTime+i);
    byteCounter++;
  }
  convertToHex(t, 7, false);

  for(int i=0; i<20; i++){
    pCache[byteCounter] = pgm_read_byte_near(minTime+i);
    byteCounter++;
  }
  convertToHex(minWriteTime, 7, false);

  for(int i=0; i<20; i++){
    pCache[byteCounter] = pgm_read_byte_near(maxTime+i);
    byteCounter++;
  }
  convertToHex(maxWriteTime, 7, false);

  for(int i=0; i<7; i++){
    pCache[byteCounter] = pgm_read_byte_near(overNum+i);
    byteCounter++;
  }
  convertToHex(overruns, 7, false);

  for(int i=0; i<11; i++){
    pCache[byteCounter] = pgm_read_byte_near(blockTime+i);
    byteCounter++;
  }

  if (overruns) {
    uint8_t n = overruns > OVER_DIM ? OVER_DIM : overruns;
    for (uint8_t i = 0; i < n; i++) {
      convertToHex(over[i].block, 7, true);
      convertToHex(over[i].micro, 7, false);
    }
  }

  for(int i=byteCounter; i<512; i++){
    pCache[i] = NULL;
  }
 
  writeCache();
}


// Change 2: tail canary at block BLOCK_COUNT-1, after writeFooter and before closeSDfile.
// Caller must ensure SD CS is HIGH on entry (we csLow ourselves).
// Caller must ensure ADS is in SDATAC (P2-3: stopADS() called before this).
static void writeTailCanary() {
  memset(pCache, 0x00, 512);
  {
    const char kTail[16] = {'O','B','C','I','_','T','A','I','L','_','V','0','1', 0, 0, 0};
    memcpy(pCache, kTail, 16);
  }
  uint32_t ts = millis();
  pCache[16] = (ts      ) & 0xFF;
  pCache[17] = (ts >>  8) & 0xFF;
  pCache[18] = (ts >> 16) & 0xFF;
  pCache[19] = (ts >> 24) & 0xFF;
  pCache[20] = board.sampleCounter;
  pCache[21] = (overruns      ) & 0xFF;
  pCache[22] = (overruns >>  8) & 0xFF;
  pCache[23] = (overruns >> 16) & 0xFF;
  pCache[24] = (overruns >> 24) & 0xFF;

  board.csLow(SD_SS);
  const bool ok = card.writeData(pCache);
  board.csHigh(SD_SS);
  if (!ok && !board.streaming) {
    Serial0.print("$SDERR:TAIL_FAIL$$$");
  }
  // Regardless of outcome: fall through to closeSDfile() which does writeStop.
}


//    CONVERT RAW BYTE DATA TO HEX FOR SD STORAGE
void convertToHex(long rawData, int numNibbles, boolean useComma){

  for (int currentNibble = numNibbles; currentNibble >= 0; currentNibble--){
    byte nibble = (rawData >> currentNibble*4) & 0x0F;
    if (nibble > 9){
      nibble += 55;  // convert to ASCII A-F
    }
    else{
      nibble += 48;  // convert to ASCII 0-9
    }
    pCache[byteCounter] = nibble;
    byteCounter++;
    if(byteCounter == 512){
      writeCache();
    }
  }
  if(useComma == true){
    pCache[byteCounter] = ',';
  }else{
    pCache[byteCounter] = '\n';
  }
  byteCounter++;
  if(byteCounter == 512){
    writeCache();
  }
}// end of byteToHex converter
