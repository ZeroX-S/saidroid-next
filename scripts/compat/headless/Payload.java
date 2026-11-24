package org.saildroid.compat;

import android.os.Parcel;
import android.os.Parcelable;

public final class Payload implements Parcelable {
    public final String value;
    public Payload(String value) { this.value = value; }
    public void writeToParcel(Parcel parcel, int flags) { parcel.writeString(value); }
    public int describeContents() { return 0; }
    public static final Creator<Payload> CREATOR = new Creator<Payload>() {
        public Payload createFromParcel(Parcel parcel) { return new Payload(parcel.readString()); }
        public Payload[] newArray(int size) { return new Payload[size]; }
    };
}
