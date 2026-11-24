import android.hardware.input.InputManager;
import android.view.InputDevice;
import android.view.KeyCharacterMap;
import android.view.KeyEvent;

/** Runs in the actual API29 ART/native framework without mapping a window. */
public final class InputManagerContract {
    private static void require(boolean value,String message){if(!value)throw new AssertionError(message);}
    public static void main(String[] args){try{
        SdRuntime.initializeFramework(true);SdServices.installAll();
        InputManager manager=InputManager.getInstance();
        require(manager.getInputDevice(-1).isVirtual(),"virtual keyboard identity");
        require(manager.getInputDevice(0).supportsSource(InputDevice.SOURCE_TOUCHSCREEN),"touch bridge source");
        require(manager.getInputDevice(424242)==null,"unknown device must be absent");
        KeyCharacterMap map=KeyCharacterMap.load(KeyCharacterMap.VIRTUAL_KEYBOARD);
        require(map.getKeyboardType()==KeyCharacterMap.FULL,"real native FULL map");
        require(map.get(KeyEvent.KEYCODE_A,0)=='a',"lowercase");
        require(map.get(KeyEvent.KEYCODE_A,KeyEvent.META_SHIFT_ON)=='A',"shift");
        require(map.get(KeyEvent.KEYCODE_A,KeyEvent.META_CAPS_LOCK_ON)=='A',"caps lock");
        require(map.get(KeyEvent.KEYCODE_A,KeyEvent.META_CAPS_LOCK_ON|KeyEvent.META_SHIFT_ON)=='a',"caps plus shift");
        require(map.get(KeyEvent.KEYCODE_1,KeyEvent.META_SHIFT_ON)=='!',"shifted digit");
        require(map.getEvents("aA1![]".toCharArray())!=null,"native character to event conversion");
        require(new KeyEvent(KeyEvent.ACTION_DOWN,KeyEvent.KEYCODE_DEL).getUnicodeChar()==0,"nonprinting backspace uses InputManager");
        require(new KeyEvent(KeyEvent.ACTION_DOWN,KeyEvent.KEYCODE_DPAD_LEFT).getUnicodeChar()==0,"cursor key uses InputManager");
        require(KeyCharacterMap.load(424242).get(KeyEvent.KEYCODE_A,0)=='a',"unknown KeyEvent device falls back to virtual map");
        boolean[] present=manager.deviceHasKeys(-1,new int[]{KeyEvent.KEYCODE_DEL,KeyEvent.KEYCODE_CAMERA});
        require(present[0]&&!present[1],"supported key inventory");
        System.out.println("INPUT_MANAGER_CONTRACT=PASS|native_kcm=true|backspace=true|cursor=true|shift=true|unknown_device=true");System.exit(0);
    }catch(Throwable error){error.printStackTrace();System.exit(11);}}
}
