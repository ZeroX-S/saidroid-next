/*
 * Copyright (C) 2010 The Android Open Source Project
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *      http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */

// AOSP jitter buffer, RTP framing, mixing, and telephone-event transmission.
int gRandom = -1;

// We use a circular array to implement jitter buffer. The simplest way is doing
// a modulo operation on the index while accessing the array. However modulo can
// be expensive on some platforms, such as ARM. Thus we round up the size of the
// array to the nearest power of 2 and then use bitwise-and instead of modulo.
// Currently we make it 2048ms long and assume packet interval is 50ms or less.
// The first 100ms is the place where samples get mixed. The rest is the real
// jitter buffer. For a stream at 8000Hz it takes 32 kilobytes. These numbers
// are chosen by experiments and each of them can be adjusted as needed.

// Originally a stream does not send packets when it is receive-only or there is
// nothing to mix. However, this causes some problems with certain firewalls and
// proxies. A firewall might remove a port mapping when there is no outgoing
// packet for a preiod of time, and a proxy might wait for incoming packets from
// both sides before start forwarding. To solve these problems, we send out a
// silence packet on the stream for every second. It should be good enough to
// keep the stream alive with relatively low resources.

// Other notes:
// + We use elapsedRealtime() to get the time. Since we use 32bit variables
//   instead of 64bit ones, comparison must be done by subtraction.
// + Sampling rate must be multiple of 1000Hz, and packet length must be in
//   milliseconds. No floating points.
// + If we cannot get enough CPU, we drop samples and simulate packet loss.
// + Resampling is not done yet, so streams in one group must use the same rate.
//   For the first release only 8000Hz is supported.

#define BUFFER_SIZE     2048
#define HISTORY_SIZE    100
#define MEASURE_BASE    100
#define MEASURE_PERIOD  5000
#define DTMF_PERIOD     200

class AudioStream
{
public:
    AudioStream();
    ~AudioStream();
    bool set(int mode, int socket, sockaddr_storage *remote,
        AudioCodec *codec, int sampleRate, int sampleCount,
        int codecType, int dtmfType);

    void sendDtmf(int event);
    bool mix(int32_t *output, int head, int tail, int sampleRate);
    void encode(int tick, AudioStream *chain);
    void decode(int tick);

private:
    enum {
        NORMAL = 0,
        SEND_ONLY = 1,
        RECEIVE_ONLY = 2,
        LAST_MODE = 2,
    };

    int mMode;
    int mSocket;
    sockaddr_storage mRemote;
    AudioCodec *mCodec;
    uint32_t mCodecMagic;
    uint32_t mDtmfMagic;
    bool mFixRemote;

    int mTick;
    int mSampleRate;
    int mSampleCount;
    int mInterval;
    int mKeepAlive;

    int16_t *mBuffer;
    int mBufferMask;
    int mBufferHead;
    int mBufferTail;
    int mLatencyTimer;
    int mLatencyScore;

    uint16_t mSequence;
    uint32_t mTimestamp;
    uint32_t mSsrc;

    int mDtmfEvent;
    int mDtmfStart;

    AudioStream *mNext;

    friend class AudioGroup;
};

AudioStream::AudioStream()
{
    mSocket = -1;
    mCodec = NULL;
    mBuffer = NULL;
    mNext = NULL;
}

AudioStream::~AudioStream()
{
    close(mSocket);
    delete mCodec;
    delete [] mBuffer;
    ALOGD("stream[%d] is dead", mSocket);
}

bool AudioStream::set(int mode, int socket, sockaddr_storage *remote,
    AudioCodec *codec, int sampleRate, int sampleCount,
    int codecType, int dtmfType)
{
    if (mode < 0 || mode > LAST_MODE) {
        return false;
    }
    mMode = mode;

    mCodecMagic = (0x8000 | codecType) << 16;
    mDtmfMagic = (dtmfType == -1) ? 0 : (0x8000 | dtmfType) << 16;

    mTick = elapsedRealtime();
    mSampleRate = sampleRate / 1000;
    mSampleCount = sampleCount;
    mInterval = mSampleCount / mSampleRate;

    // Allocate jitter buffer.
    for (mBufferMask = 8; mBufferMask < mSampleRate; mBufferMask <<= 1);
    mBufferMask *= BUFFER_SIZE;
    mBuffer = new int16_t[mBufferMask];
    --mBufferMask;
    mBufferHead = 0;
    mBufferTail = 0;
    mLatencyTimer = 0;
    mLatencyScore = 0;
    mKeepAlive = 0;

    // Initialize random bits.
    read(gRandom, &mSequence, sizeof(mSequence));
    read(gRandom, &mTimestamp, sizeof(mTimestamp));
    read(gRandom, &mSsrc, sizeof(mSsrc));

    mDtmfEvent = -1;
    mDtmfStart = 0;

    // Only take over these things when succeeded.
    mSocket = socket;
    if (codec) {
        mRemote = *remote;
        mCodec = codec;

        // Here we should never get an private address, but some buggy proxy
        // servers do give us one. To solve this, we replace the address when
        // the first time we successfully decode an incoming packet.
        mFixRemote = false;
        if (remote->ss_family == AF_INET) {
            unsigned char *address =
                (unsigned char *)&((sockaddr_in *)remote)->sin_addr;
            if (address[0] == 10 ||
                (address[0] == 172 && (address[1] >> 4) == 1) ||
                (address[0] == 192 && address[1] == 168)) {
                mFixRemote = true;
            }
        }
    }

    ALOGD("stream[%d] is configured as %s %dkHz %dms mode %d", mSocket,
        (codec ? codec->name : "RAW"), mSampleRate, mInterval, mMode);
    return true;
}

void AudioStream::sendDtmf(int event)
{
    if (mDtmfMagic != 0) {
        mDtmfEvent = event << 24;
        mDtmfStart = mTimestamp + mSampleCount;
    }
}

bool AudioStream::mix(int32_t *output, int head, int tail, int sampleRate)
{
    if (mMode == SEND_ONLY) {
        return false;
    }

    if (head - mBufferHead < 0) {
        head = mBufferHead;
    }
    if (tail - mBufferTail > 0) {
        tail = mBufferTail;
    }
    if (tail - head <= 0) {
        return false;
    }

    head *= mSampleRate;
    tail *= mSampleRate;

    if (sampleRate == mSampleRate) {
        for (int i = head; i - tail < 0; ++i) {
            output[i - head] += mBuffer[i & mBufferMask];
        }
    } else {
        // TODO: implement resampling.
        return false;
    }
    return true;
}

void AudioStream::encode(int tick, AudioStream *chain)
{
    if (tick - mTick >= mInterval) {
        // We just missed the train. Pretend that packets in between are lost.
        int skipped = (tick - mTick) / mInterval;
        mTick += skipped * mInterval;
        mSequence += skipped;
        mTimestamp += skipped * mSampleCount;
        ALOGV("stream[%d] skips %d packets", mSocket, skipped);
    }

    tick = mTick;
    mTick += mInterval;
    ++mSequence;
    mTimestamp += mSampleCount;

    // If there is an ongoing DTMF event, send it now.
    if (mMode != RECEIVE_ONLY && mDtmfEvent != -1) {
        int duration = mTimestamp - mDtmfStart;
        // Make sure duration is reasonable.
        if (duration >= 0 && duration < mSampleRate * DTMF_PERIOD) {
            duration += mSampleCount;
            int32_t buffer[4] = {
                static_cast<int32_t>(htonl(mDtmfMagic | mSequence)),
                static_cast<int32_t>(htonl(mDtmfStart)),
                static_cast<int32_t>(mSsrc),
                static_cast<int32_t>(htonl(mDtmfEvent | duration)),
            };
            if (duration >= mSampleRate * DTMF_PERIOD) {
                buffer[3] |= htonl(1 << 23);
                mDtmfEvent = -1;
            }
            sendto(mSocket, buffer, sizeof(buffer), MSG_DONTWAIT,
                (sockaddr *)&mRemote, sizeof(mRemote));
            return;
        }
        mDtmfEvent = -1;
    }

    int32_t buffer[mSampleCount + 3];
    bool data = false;
    if (mMode != RECEIVE_ONLY) {
        // Mix all other streams.
        memset(buffer, 0, sizeof(buffer));
        while (chain) {
            if (chain != this) {
                data |= chain->mix(buffer, tick - mInterval, tick, mSampleRate);
            }
            chain = chain->mNext;
        }
    }

    int16_t samples[mSampleCount];
    if (data) {
        // Saturate into 16 bits.
        for (int i = 0; i < mSampleCount; ++i) {
            int32_t sample = buffer[i];
            if (sample < -32768) {
                sample = -32768;
            }
            if (sample > 32767) {
                sample = 32767;
            }
            samples[i] = sample;
        }
    } else {
        if ((mTick ^ mKeepAlive) >> 10 == 0) {
            return;
        }
        mKeepAlive = mTick;
        memset(samples, 0, sizeof(samples));

        if (mMode != RECEIVE_ONLY) {
            ALOGV("stream[%d] no data", mSocket);
        }
    }

    if (!mCodec) {
        // Special case for device stream.
        send(mSocket, samples, sizeof(samples), MSG_DONTWAIT);
        return;
    }

    // Cook the packet and send it out.
    buffer[0] = htonl(mCodecMagic | mSequence);
    buffer[1] = htonl(mTimestamp);
    buffer[2] = mSsrc;
    int length = mCodec->encode(&buffer[3], samples);
    if (length <= 0) {
        ALOGV("stream[%d] encoder error", mSocket);
        return;
    }
    sendto(mSocket, buffer, length + 12, MSG_DONTWAIT, (sockaddr *)&mRemote,
        sizeof(mRemote));
}

void AudioStream::decode(int tick)
{
    char c;
    if (mMode == SEND_ONLY) {
        recv(mSocket, &c, 1, MSG_DONTWAIT);
        return;
    }

    // Make sure mBufferHead and mBufferTail are reasonable.
    if ((unsigned int)(tick + BUFFER_SIZE - mBufferHead) > BUFFER_SIZE * 2) {
        mBufferHead = tick - HISTORY_SIZE;
        mBufferTail = mBufferHead;
    }

    if (tick - mBufferHead > HISTORY_SIZE) {
        // Throw away outdated samples.
        mBufferHead = tick - HISTORY_SIZE;
        if (mBufferTail - mBufferHead < 0) {
            mBufferTail = mBufferHead;
        }
    }

    // Adjust the jitter buffer if the latency keeps larger than the threshold
    // in the measurement period.
    int score = mBufferTail - tick - MEASURE_BASE;
    if (mLatencyScore > score || mLatencyScore <= 0) {
        mLatencyScore = score;
        mLatencyTimer = tick;
    } else if (tick - mLatencyTimer >= MEASURE_PERIOD) {
        ALOGV("stream[%d] reduces latency of %dms", mSocket, mLatencyScore);
        mBufferTail -= mLatencyScore;
        mLatencyScore = -1;
    }

    int count = (BUFFER_SIZE - (mBufferTail - mBufferHead)) * mSampleRate;
    if (count < mSampleCount) {
        // Buffer overflow. Drop the packet.
        ALOGV("stream[%d] buffer overflow", mSocket);
        recv(mSocket, &c, 1, MSG_DONTWAIT);
        return;
    }

    // Receive the packet and decode it.
    int16_t samples[count];
    if (!mCodec) {
        // Special case for device stream.
        count = recv(mSocket, samples, sizeof(samples),
            MSG_TRUNC | MSG_DONTWAIT) >> 1;
    } else {
        __attribute__((aligned(4))) uint8_t buffer[2048];
        sockaddr_storage remote;
        socklen_t addrlen = sizeof(remote);

        int length = recvfrom(mSocket, buffer, sizeof(buffer),
            MSG_TRUNC | MSG_DONTWAIT, (sockaddr *)&remote, &addrlen);

        // Do we need to check SSRC, sequence, and timestamp? They are not
        // reliable but at least they can be used to identify duplicates?
        if (length < 12 || length > (int)sizeof(buffer) ||
            (ntohl(*(uint32_t *)buffer) & 0xC07F0000) != mCodecMagic) {
            ALOGV("stream[%d] malformed packet", mSocket);
            return;
        }
        int offset = 12 + ((buffer[0] & 0x0F) << 2);
        if (offset > length) return;
        if ((buffer[0] & 0x10) != 0) {
            if (offset + 4 > length) return;
            offset += 4 + (ntohs(*(uint16_t *)&buffer[offset + 2]) << 2);
            if (offset > length) return;
        }
        if ((buffer[0] & 0x20) != 0) {
            int padding = buffer[length - 1];
            if (padding == 0 || padding > length - offset) return;
            length -= padding;
        }
        if (!mFixRemote && (addrlen != sizeof(sockaddr_in) && addrlen != sizeof(sockaddr_in6))) return;
        length -= offset;
        if (length >= 0) {
            length = mCodec->decode(samples, count, &buffer[offset], length);
        }
        if (length > 0 && mFixRemote) {
            mRemote = remote;
            mFixRemote = false;
        }
        count = length;
    }
    if (count <= 0) {
        ALOGV("stream[%d] decoder error", mSocket);
        return;
    }

    if (tick - mBufferTail > 0) {
        // Buffer underrun. Reset the jitter buffer.
        ALOGV("stream[%d] buffer underrun", mSocket);
        if (mBufferTail - mBufferHead <= 0) {
            mBufferHead = tick + mInterval;
            mBufferTail = mBufferHead;
        } else {
            int tail = (tick + mInterval) * mSampleRate;
            for (int i = mBufferTail * mSampleRate; i - tail < 0; ++i) {
                mBuffer[i & mBufferMask] = 0;
            }
            mBufferTail = tick + mInterval;
        }
    }

    // Append to the jitter buffer.
    int tail = mBufferTail * mSampleRate;
    for (int i = 0; i < count; ++i) {
        mBuffer[tail & mBufferMask] = samples[i];
        ++tail;
    }
    mBufferTail += count / mSampleRate;
}

