import React, { useState, useEffect } from "react";
import InfoComponentBonos from "../../../../components/InfoComponentBonos/InfoComponentBonos";
import TitleBonos from "../../../../components/TitleBonos/index";
import SliderBonos from "../../../../components/SliderBonos/index";
import BonosAdviceModal from "../../../../components/BonosAdviceModal/index";
import ModalWire from "../../../../components/ModalWire/index";
import styles from "./tv.module.css";
import useMediaQuery from "@/utils/useMediaQuery";
import InfoSliderMobile from "../../../../components/InfoSliderMobile/index";
import AhorroFibra from "../../../../components/BonosAdviceModalItem/Ahorro";
import SeguroFibra from "../../../../components/BonosAdviceModalItem/SeguroFibra";
import AdviceSliderMobile from "../../../../components/AdviceSliderMobile/index";
import { getBonosDiscounts } from "../../../../store/actions/bonos/index";
import { RootState } from "../../../../store/index";
import { useSelector } from "react-redux";
import { BonosDiscountsResponse } from "../../../../types/empleado/bonos/types";
import { useAppDispatch } from "@/store/DispatchAndSelector";
import PlanCardTV from "@/components/PlanCard/PlanCardTV";

export default function TVBonosView() {
  const dispatch = useAppDispatch();

  const [data, setData] = useState<BonosDiscountsResponse>([]);
  const [isLoading, setIsLoading] = useState(true);
  const { data: userData } = useSelector((state: RootState) => state.user);
  console.log("DATA", data);

  useEffect(() => {
    setIsLoading(true);
    dispatch(getBonosDiscounts())
      .unwrap()
      .then((bonos: any) => {
        const bonosTV = bonos.filter((bono: any) => bono.tipo.toLowerCase() === "tv");

        const extrasMap: Record<string, any> = {
          "Movistar TV Digital": "38 Canales",
          "TV Digital Combo": "con Disney+ Premium",
          "TV MAX": "98 Canales",
          "TV MAX Combo": "con Disney+ Premium",
        };

        const bonosWithExtras = bonosTV.map((bono: any) => {
          const extras = extrasMap[bono.titulo];
          return extras ? { ...bono, extras } : bono;
        });

        setData(bonosWithExtras);
      })
      .finally(() => setIsLoading(false));
  }, [dispatch]);

  const isMobile = useMediaQuery("(max-width: 768px)");

  return (
    <div className={styles.containerTelefonicaView}>
      <TitleBonos
        imageSrc="bonoTV"
        title="30% de descuento en Planes de Movistar TV"
        subtitle="Te contamos de qué se trata el beneficio de descuento en planes de TV para empleados"
      />

      <div className={styles.titleContainer}>
        <h2 className={styles.titleHelp}>
          Aquí encontrarás los valores de los planes con TV y los packs, utilizando los beneficios
          que tenés como emplead@
        </h2>
      </div>
      <SliderBonos data={data} bottomText="DECO: Máximo 3 $5600 c/u.">
        {(plan) => <PlanCardTV key={plan.titulo} plan={plan} />}
      </SliderBonos>
      <div className={styles.titleContainer}>
        <h2 className={styles.titleHelp}>Lo que tenés que saber para acceder al beneficio</h2>
      </div>
      {isMobile ? (
        // slider mobile
        <div className={styles.infoContainer}>
          <InfoSliderMobile type="hogar" />
        </div>
      ) : (
        <InfoComponentBonos type="blank">
          <ol className={styles.list}>
            <li className={styles.listItem}>
              <span className={styles.listText}>
                Los servicios tanto de internet fibra como de telefonía deben estar a nombre del
                empleado.
              </span>
            </li>
            <li className={styles.listItem}>
              <span className={styles.listText}>El empleado no debe tener deuda con Movistar.</span>
            </li>
            <li className={styles.listItem}>
              <span className={styles.listText}>
                Para solicitar el Beneficio, hace un posteo en el grupo de{" "}
                <a href="https://engage.cloud.microsoft/main/org/tmoviles.com.ar/groups/eyJfdHlwZSI6Ikdyb3VwIiwiaWQiOiIyMzM3MDM0MTU4MDgifQ">
                  {" "}
                  AR – Experiencia Empleados en VIVA
                </a>{" "}
                indicando tu solicitud. A la brevedad, te contactaran para gestionar tu pedido.
              </span>
            </li>
          </ol>
        </InfoComponentBonos>
      )}
    </div>
  );
}
