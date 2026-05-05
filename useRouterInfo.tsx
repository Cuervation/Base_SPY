import { UserRole } from "@/types";
import { ButtonPrimary } from "@telefonica/mistica";
import Router, { NextRouter, useRouter } from "next/router";
import React, { useState } from "react";

export type RouterInfo = {
  pageTitle: string;
  header: string;
  breadcrumbs: Array<{
    readonly title: string;
    readonly url: string;
  }>;
  headerExtraComponents?: any[];
  hiddeArrowBack?: boolean;
  goBackTo?: string;
};

const pageTitleBase = "App Beneficios";

export type RoutesInfoType = {
  [index: string]: RouterInfo;
};

const routesInfo: RoutesInfoType = {
  default: {
    pageTitle: pageTitleBase,
    header: pageTitleBase,
    breadcrumbs: [],
  },
  "/": {
    pageTitle: pageTitleBase + " | Inicio",
    header: " ",
    breadcrumbs: [],
    hiddeArrowBack: true,
  },
  "/empleado/insignias": {
    pageTitle: pageTitleBase + " | Mis Reconocimientos",
    header: "",
    breadcrumbs: [],
    hiddeArrowBack: true,
  },
  "/empleado/perfil/[email]": {
    pageTitle: pageTitleBase + " | Perfil",
    header: "",
    breadcrumbs: [],
    hiddeArrowBack: true,
  },
  "/abm/empleado/configuraciones": {
    pageTitle: pageTitleBase + " | Configuración",
    header: "Mi perfil",
    breadcrumbs: [
      { title: "Inicio", url: "/" },
      { title: "Configuración", url: "/abm/empleado/configuraciones" },
    ],
    goBackTo: "/",
  },
  "/abm/empleado/configuraciones/perfil": {
    pageTitle: pageTitleBase + " | Configuración - Mi perfil",
    header: "Mi perfil",
    breadcrumbs: [
      { title: "Inicio", url: "/" },
      { title: "Configuración", url: "/abm/empleado/configuraciones" },
      { title: "Mi perfil", url: "" },
    ],
    goBackTo: "/abm/empleado/configuraciones",
  },
  "/feedback": {
    hiddeArrowBack: true,
    breadcrumbs: [],
    header: "",
    pageTitle: "",
  },
  "/404": {
    pageTitle: pageTitleBase + " | Error 404",
    header: "Pagina no encontrada",
    breadcrumbs: [],
  },
  "/empleado/cajanavidena": {
    header: "Caja Navideña",
    pageTitle: pageTitleBase + " | Caja Navideña",
    breadcrumbs: [
      { title: "Inicio", url: "/" },
      { title: "Caja Navideña", url: "" },
    ],
    hiddeArrowBack: true,
  },
  "/empleado/kitescolar": {
    header: "Kit Escolar",
    pageTitle: pageTitleBase + " | Kit Escolar",
    breadcrumbs: [
      { title: "Inicio", url: "/" },
      { title: "Kit Escolar", url: "" },
    ],
    hiddeArrowBack: true,
  },
  "/empleado/coloniavacaciones": {
    header: "Colonia de Vacaciones",
    pageTitle: pageTitleBase + " | Colonia de Vacaciones",
    breadcrumbs: [
      { title: "Inicio", url: "/" },
      { title: "Colonia de Vacaciones", url: "" },
    ],
  },
  "/empleado/coloniavacaciones/detallefactura/[id]": {
    header: "Detalle de factura",
    pageTitle: pageTitleBase + " | Detalle de factura",
    breadcrumbs: [
      { title: "Inicio", url: "/" },
      { title: "Colonia de Vacaciones", url: "/empleado/coloniavacaciones" },
      { title: "Detalle de factura", url: "" },
    ],
    goBackTo: "/empleado/coloniavacaciones",
  },
  "/empleado/coloniavacaciones/subirfactura": {
    header: "Subir factura",
    pageTitle: pageTitleBase + " | Subir factura",
    breadcrumbs: [
      { title: "Inicio", url: "/" },
      { title: "Colonia de Vacaciones", url: "/empleado/coloniavacaciones" },
      { title: "Subir factura", url: "" },
    ],
    goBackTo: "/empleado/coloniavacaciones",
  },
  "/empleado/sorteos": {
    header: "Sorteos",
    pageTitle: pageTitleBase + " | Sorteos",
    breadcrumbs: [
      { title: "Inicio", url: "/" },
      { title: "Sorteos", url: "" },
    ],
  },
  "/empleado/sorteos/[id]": {
    header: "Sorteos",
    pageTitle: pageTitleBase + " | Sorteos",
    breadcrumbs: [
      { title: "Inicio", url: "/" },
      { title: "Sorteos", url: "/empleado/sorteos" },
    ],
  },
  "/empleado/sorteos?id=claim": {
    header: "Sorteos",
    pageTitle: pageTitleBase + " | Sorteos",
    breadcrumbs: [
      { title: "Inicio", url: "/" },
      { title: "Sorteos", url: "" },
    ],
  },
  "/empleado/eventos": {
    header: "Eventos",
    pageTitle: pageTitleBase + " | Eventos",
    breadcrumbs: [
      { title: "Inicio", url: "/" },
      { title: "Eventos", url: "" },
    ],
  },
  "/empleado/cursos": {
    header: "Cursos",
    pageTitle: pageTitleBase + " | Cursos",
    breadcrumbs: [
      { title: "Inicio", url: "/" },
      { title: "Cursos", url: "" },
    ],
  },
  "/empleado/seguros/modificacionBeneficiarios": {
    header: "Designación/Modifiación de Beneficiarios",
    pageTitle: pageTitleBase + " | Designación/Modifiación de Beneficiarios",
    breadcrumbs: [
      { title: "Inicio", url: "/" },
      { title: "Seguros", url: "" },
      { title: "Designación/Modifiación de Beneficiarios", url: "" },
    ],
  },
  "/empleado/seguros/gestionarSeguros": {
    header: "Gestionar Seguros",
    pageTitle: pageTitleBase + " | Gestionar Seguros",
    breadcrumbs: [
      { title: "Inicio", url: "/" },
      { title: "Seguros", url: "" },
      { title: "Gestionar Seguros", url: "" },
    ],
  },
  "/empleado/eventos?id=claim": {
    header: "Eventos",
    pageTitle: pageTitleBase + " | Eventos",
    breadcrumbs: [
      { title: "Inicio", url: "/" },
      { title: "Eventos", url: "" },
    ],
  },
  "/empleado/tickets": {
    header: "Mis Entradas",
    pageTitle: pageTitleBase + " | Entradas",
    breadcrumbs: [
      { title: "Inicio", url: "/" },
      { title: "Entradas", url: "" },
    ],
  },
  "/empleado/bonos": {
    header: "Descuentos Movistar ",
    pageTitle: pageTitleBase + " | Descuentos Movistar",
    breadcrumbs: [
      { title: "Inicio", url: "/" },
      {
        title: "Mis oportunidades y descuentos",
        url: "/empleado/oportunidades-descuentos",
      },
      { title: "Descuentos Movistar", url: "/empleado/bonos" },
    ],
  },
  "/empleado/bonos/telefonia": {
    header: "Telefonia",
    pageTitle: pageTitleBase + " | Telefonia",
    breadcrumbs: [
      { title: "Inicio", url: "/" },
      {
        title: "Mis oportunidades y descuentos",
        url: "/empleado/oportunidades-descuentos",
      },
      { title: "Descuentos Movistar", url: "/empleado/bonos/" },
    ],
    goBackTo: "/empleado/bonos",
  },
  "/empleado/bonos/seguros": {
    header: "Seguros",
    pageTitle: pageTitleBase + " | Seguros",
    breadcrumbs: [
      { title: "Inicio", url: "/" },
      {
        title: "Mis oportunidades y descuentos",
        url: "/empleado/oportunidades-descuentos",
      },
      { title: "Descuentos Movistar", url: "/empleado/bonos/" },
    ],
    goBackTo: "/empleado/bonos",
  },
  "/empleado/bonos/hogar": {
    header: "Hogar",
    pageTitle: pageTitleBase + " | Hogar",
    breadcrumbs: [
      { title: "Inicio", url: "/" },
      {
        title: "Mis oportunidades y descuentos",
        url: "/empleado/oportunidades-descuentos",
      },
      { title: "Descuentos Movistar", url: "/empleado/bonos/" },
    ],
    goBackTo: "/empleado/bonos",
  },
  "/empleado/bonos/TV": {
    header: "Descuentos en tv",
    pageTitle: pageTitleBase + " | TV",
    breadcrumbs: [
      { title: "Inicio", url: "/" },
      {
        title: "Mis oportunidades y descuentos",
        url: "/empleado/oportunidades-descuentos",
      },
      { title: "Descuentos Movistar", url: "/empleado/bonos/" },
    ],
    goBackTo: "/empleado/bonos",
  },
  "/empleado/bonos/movistarcontodo": {
    header: "Movistar con todo",
    pageTitle: pageTitleBase + " | Hogar",
    breadcrumbs: [
      { title: "Inicio", url: "/" },
      {
        title: "Mis oportunidades y descuentos",
        url: "/empleado/oportunidades-descuentos",
      },
      { title: "Descuentos Movistar", url: "/empleado/bonos/" },
    ],
    goBackTo: "/empleado/bonos",
  },
  "/abm/prensa/tickets": {
    header: "Entrega de tickets",
    pageTitle: pageTitleBase + " | Entrega de Tickets",
    breadcrumbs: [
      { title: "Inicio", url: "/" },
      { title: "Entrega", url: "" },
    ],
  },

  "/empleado/fibra": {
    header: "Disponibilidad Fibra",
    pageTitle: pageTitleBase + " | Fibra",
    breadcrumbs: [
      { title: "Inicio", url: "/" },
      { title: "Disponibilidad de Fibra", url: "" },
    ],
  },
  "/empleado/oportunidades-descuentos": {
    header: "Mis oportunidades y descuentos",
    pageTitle: pageTitleBase + " | Oportunidades y descuentos",
    breadcrumbs: [
      { title: "Inicio", url: "/" },
      {
        title: "Mis oportunidades y descuentos",
        url: "/empleado/oportunidades-descuentos",
      },
    ],
  },
  "/empleado/descuentos": {
    header: "Cupones y descuentos",
    pageTitle: pageTitleBase + " | Cupones y descuentos",
    breadcrumbs: [
      { title: "Inicio", url: "/" },
      {
        title: "Mis oportunidades y descuentos",
        url: "/empleado/oportunidades-descuentos",
      },
      { title: "Cupones y descuentos", url: "/empleado/descuentos" },
    ],
  },
  "/empleado/beneficiosfamilia": {
    header: "Mis beneficios en familia",
    pageTitle: pageTitleBase + " | Beneficios en familia",
    breadcrumbs: [
      { title: "Inicio", url: "/" },
      {
        title: "Mis beneficios en familia",
        url: "/empleado/oportunidades-descuentos",
      },
    ],
  },
  "/empleado/beneficiosfamilia/obsequionacimiento": {
    header: "Obsequio por nacimiento",
    pageTitle: pageTitleBase + " | Beneficios en familia",
    breadcrumbs: [
      { title: "Inicio", url: "/" },
      {
        title: "Mis beneficios en familia",
        url: "/empleado/beneficiosfamilia",
      },
      {
        title: "Obsequio por nacimiento",
        url: "/empleado/beneficiosfamilia/obsequionacimiento",
      },
    ],
  },
  "/empleado/beneficiosfamilia/vueltaalcole": {
    header: "Vuelta al cole",
    pageTitle: pageTitleBase + " | Beneficios en familia",
    breadcrumbs: [
      { title: "Inicio", url: "/" },
      {
        title: "Mis beneficios en familia",
        url: "/empleado/beneficiosfamilia",
      },
      {
        title: "Vuelta al cole",
        url: "/empleado/beneficiosfamilia/vueltaalcole",
      },
    ],
  },
  "/empleado/beneficiosfamilia/guarderia": {
    header: "Guarderia",
    pageTitle: pageTitleBase + " | Beneficios en familia",
    breadcrumbs: [
      { title: "Inicio", url: "/" },
      {
        title: "Mis beneficios en familia",
        url: "/empleado/beneficiosfamilia",
      },
      { title: "Guarderia", url: "/empleado/beneficiosfamilia/guarderia" },
    ],
  },
  "/empleado/beneficiosfamilia/obsequiofindeano": {
    header: "Obsequio de fin de año",
    pageTitle: pageTitleBase + " | Beneficios en familia",
    breadcrumbs: [
      { title: "Inicio", url: "/" },
      {
        title: "Mis beneficios en familia",
        url: "/empleado/beneficiosfamilia",
      },
      {
        title: "Obsequio de fin de año",
        url: "/empleado/beneficiosfamilia/obsequiofindeano",
      },
    ],
  },
  "/empleado/beneficiosfamilia/coloniadevacaciones": {
    header: "Colonia de verano",
    pageTitle: pageTitleBase + " | Beneficios en familia",
    breadcrumbs: [
      { title: "Inicio", url: "/" },
      {
        title: "Mis beneficios en familia",
        url: "/empleado/beneficiosfamilia",
      },
      {
        title: "Colonia de verano",
        url: "/empleado/beneficiosfamilia/coloniadevacaciones",
      },
    ],
  },
  "/empleado/beneficiosfamilia/movistararena": {
    header: "Movistar Arena",
    pageTitle: pageTitleBase + " | Beneficios en familia",
    breadcrumbs: [
      { title: "Inicio", url: "/" },
      {
        title: "Mis beneficios en familia",
        url: "/empleado/beneficiosfamilia",
      },
      {
        title: "Movistar Arena",
        url: "/empleado/beneficiosfamilia/movistararena",
      },
    ],
  },
  "/empleado/gestionreferidos": {
    pageTitle: pageTitleBase + " | Gestión de bienes",
    header: "Referir bienes",
    breadcrumbs: [
      { title: "Inicio", url: "/" },
      { title: "Gestión de bienes", url: "/" },
      { title: "Referir bienes", url: "/empleado/gestionreferidos" },
    ],
  },
  "/empleado/gestionreferidos/[id]": {
    pageTitle: pageTitleBase + " | Gestión de bienes",
    header: "Detalle de solicitud",
    breadcrumbs: [
      { title: "Inicio", url: "/" },
      { title: "Gestión de bienes", url: "/" },
      { title: "Solicitudes recibidas", url: "/empleado/gestionreferidos/" },
      { title: "Detalle de solicitud", url: "/empleado/gestionreferidos/[id]" },
    ],
  },
  "/empleado/gestionreferidos/referir": {
    pageTitle: pageTitleBase + " | Gestión de bienes",
    header: "Referir un bien",
    breadcrumbs: [
      { title: "Inicio", url: "/" },
      { title: "Gestión de bienes", url: "/" },
      { title: "Referir bienes", url: "/empleado/gestionreferidos" },
      { title: "Referir un bien", url: "/empleado/gestionreferidos/referir" },
    ],
  },
  "/abm/fibra": {
    header: "Solicitudes de Fibra",
    pageTitle: pageTitleBase + " | Solicitudes de Fibra",
    breadcrumbs: [
      { title: "Inicio", url: "/" },
      { title: "Solicitudes", url: "" },
    ],
  },
  "/abm/bonos": {
    header: "Descuentos Movistar",
    pageTitle: pageTitleBase + " | Descuentos Movistar",
    breadcrumbs: [
      { title: "Inicio", url: "/" },
      { title: "Administrar Descuentos", url: "" },
    ],
  },
  "/abm/facilitador/cajanavidena/entrega": {
    pageTitle: pageTitleBase + " | Entregar Caja Navideña",
    header: "Entregar Caja Navideña",
    breadcrumbs: [
      { title: "Inicio", url: "/" },
      { title: "Entrega", url: "" },
    ],
    hiddeArrowBack: true,
  },
  "/abm/facilitador/reportes": {
    pageTitle: "Reportes",
    header: "Reportes",
    breadcrumbs: [{ title: "Inicio", url: "/" }],
    hiddeArrowBack: true,
  },
  "/abm/admin/importar": {
    pageTitle: pageTitleBase + " | Importar Datos",
    header: "Importar Datos",
    breadcrumbs: [
      { title: "Inicio", url: "/" },
      { title: "Importar", url: "" },
    ],
    hiddeArrowBack: true,
  },
  "/abm/admin/campanas": {
    pageTitle: pageTitleBase + " | Administrar Campañas",
    header: "Administrar Campañas",
    breadcrumbs: [
      { title: "Inicio", url: "/" },
      { title: "Campañas", url: "" },
    ],
    hiddeArrowBack: true,
  },
  "/abm/admin/campanas/editar/[id]": {
    pageTitle: pageTitleBase + " | Editar Campaña",
    header: "Editar Campaña",
    breadcrumbs: [
      { title: "Inicio", url: "/" },
      { title: "Campañas", url: "/abm/admin/campanas" },
    ],
    headerExtraComponents: [],
    goBackTo: "/abm/admin/campanas",
  },
  "/abm/admin/sorteos": {
    pageTitle: pageTitleBase + " | Administrar Sorteos",
    header: "Administrar Sorteos",
    breadcrumbs: [
      { title: "Inicio", url: "/" },
      { title: "Sorteos", url: "/abm/admin/sorteos" },
    ],
    headerExtraComponents: [
      <ButtonPrimary
        className="floating-btn"
        onPress={() => {
          Router.push("/abm/admin/sorteos/nuevosorteo");
        }}
        style={{
          padding: "6px",
          position: "static",
          display: "inline-block",
          minWidth: "150px",
          textAlign: "center",
        }}
        key={"header-btn"}
      >
        Nuevo Sorteo
      </ButtonPrimary>,
    ],
    goBackTo: "/",
  },
  "/abm/admin/sorteos/nuevosorteo": {
    pageTitle: pageTitleBase + " | Nuevo Sorteo",
    header: "Nuevo Sorteo",
    breadcrumbs: [
      { title: "Inicio", url: "/" },
      { title: "Sorteos", url: "/abm/admin/sorteos" },
      { title: "Nuevo Sorteo", url: "/abm/admin/sorteos/nuevosorteo" },
    ],
  },
  "/abm/admin/sorteos/editarsorteo/[id]": {
    pageTitle: pageTitleBase + " | Editar Sorteo",
    header: "Editar Sorteo",
    breadcrumbs: [
      { title: "Inicio", url: "/" },
      { title: "Sorteos", url: "/abm/admin/sorteos" },
      { title: "Editar Sorteo", url: "/abm/admin/sorteos/editarsorteo[id]" },
    ],
  },
  "/abm/facilitador/kitescolar/entrega": {
    pageTitle: pageTitleBase + " | Entregar Kit Escolar",
    header: "Entregar Kit Escolar",
    breadcrumbs: [
      { title: "Inicio", url: "/" },
      { title: "Entrega", url: "" },
    ],
    hiddeArrowBack: true,
  },
  "/abm/facilitador/cajanavidena/entrega/steps": {
    pageTitle: pageTitleBase + " | Entregar Caja Navideña",
    header: "Entregar Caja Navideña",
    breadcrumbs: [
      { title: "Inicio", url: "/" },
      { title: "Entrega", url: "" },
    ],
  },
  "/abm/facilitador/kitescolar/entrega/steps": {
    pageTitle: pageTitleBase + " | Entregar Kit Escolar",
    header: "Entregar Kit Escolar",
    breadcrumbs: [
      { title: "Inicio", url: "/" },
      { title: "Entrega", url: "" },
    ],
  },
  "/abm/admin/facilitadores": {
    pageTitle: pageTitleBase + " | Facilitadores",
    header: "Facilitadores",
    breadcrumbs: [
      { title: "Inicio", url: "/" },
      { title: "Facilitadores", url: "" },
    ],
    headerExtraComponents: [
      <ButtonPrimary
        className="floating-btn"
        onPress={() => {
          Router.push("/abm/admin/facilitadores/nuevofacilitador");
        }}
        style={{
          padding: "6px",
          position: "static",
          display: "inline-block",
          minWidth: "100px",
          textAlign: "center",
        }}
        key={"header-btn"}
      >
        Nuevo +
      </ButtonPrimary>,
    ],
    hiddeArrowBack: true,
  },
  "/abm/admin/facilitadores/": {
    pageTitle: pageTitleBase + " | Nuevo Facilitador",
    header: "Nuevo Facilitador",
    breadcrumbs: [
      { title: "Inicio", url: "/" },
      { title: "Facilitadores", url: "/abm/admin/facilitadores/" },
      { title: "Nuevo", url: "" },
    ],
  },
  "/abm/admin/facilitadores/editarfacilitador": {
    pageTitle: pageTitleBase + " | Editar Facilitador",
    header: "Editar Facilitador",
    breadcrumbs: [
      { title: "Inicio", url: "/" },
      { title: "Facilitadores", url: "/abm/admin/facilitadores/" },
      { title: "Editar", url: "" },
    ],
  },
  "/abm/admin/facilitadores/nuevofacilitador": {
    pageTitle: pageTitleBase + " | Nuevo Facilitador",
    header: "Nuevo Facilitador",
    breadcrumbs: [
      { title: "Inicio", url: "/" },
      { title: "Facilitadores", url: "/abm/admin/facilitadores/" },
      { title: "Nuevo", url: "" },
    ],
  },
  "/abm/admin/empleados": {
    pageTitle: pageTitleBase + " | Empleados",
    header: "Empleados",
    breadcrumbs: [
      { title: "Inicio", url: "/" },
      { title: "Empleados", url: "/" },
    ],
    headerExtraComponents: [
      <ButtonPrimary
        className="floating-btn"
        onPress={() => {
          Router.push("/abm/admin/empleados/nuevoempleado");
        }}
        style={{
          padding: "6px",
          position: "static",
          display: "inline-block",
          minWidth: "100px",
          textAlign: "center",
        }}
        key={"header-btn"}
      >
        Nuevo +
      </ButtonPrimary>,
    ],
    hiddeArrowBack: true,
  },

  "/abm/admin/empleados/nuevoempleado": {
    pageTitle: pageTitleBase + " | Nuevo Empleado",
    header: "Nuevo Empleado",
    breadcrumbs: [
      { title: "Inicio", url: "/" },
      { title: "Empleados", url: "/abm/admin/empleados/" },
      { title: "Nuevo", url: "" },
    ],
  },
  "/abm/admin/empleados/editarempleado/[dni]": {
    pageTitle: pageTitleBase + " | Editar Empleado",
    header: "Editar Empleado",
    breadcrumbs: [
      { title: "Inicio", url: "/" },
      { title: "Empleados", url: "/abm/admin/empleados/" },
      { title: "Editar", url: "" },
    ],
  },
  "/abm/admin/empleados/hijos/[id]": {
    pageTitle: pageTitleBase + " | Hijos de ",
    header: "Hijos de ",
    breadcrumbs: [
      { title: "Inicio", url: "/" },
      { title: "Empleados", url: "/abm/admin/empleados/" },
      { title: "Hijos", url: "" },
    ],

    headerExtraComponents: [
      (router: NextRouter) => {
        const { id } = router.query;
        return (
          <ButtonPrimary
            className="floating-btn"
            onPress={() => {
              Router.push("/abm/admin/empleados/hijos/agregarhijo/" + id);
            }}
            style={{
              padding: "6px",
              position: "static",
              display: "inline-block",
              minWidth: "100px",
              textAlign: "center",
            }}
            key={"header-btn"}
          >
            Nuevo +
          </ButtonPrimary>
        );
      },
    ],
    goBackTo: "/abm/admin/empleados",
  },
  "/abm/admin/empleados/hijos/agregarhijo/[id]": {
    pageTitle: pageTitleBase + " | Agregar Hijo ",
    header: "Agregar Hijo " + " ",
    breadcrumbs: [
      { title: "Inicio", url: "/" },
      { title: "Empleados", url: "/abm/admin/empleados/" },
      { title: "Hijos", url: "/" },
      { title: "Nuevo", url: "" },
    ],
  },
  "/abm/admin/empleados/hijos/editarhijo": {
    pageTitle: pageTitleBase + " | Editar hijo",
    header: "Editar hijo",
    breadcrumbs: [
      { title: "Inicio", url: "/" },
      { title: "Empleados", url: "/abm/admin/empleados/" },
      { title: "Hijos", url: "" },
      { title: "Editar", url: "" },
    ],
  },

  "/abm/admin/empleados-kit": {
    pageTitle: pageTitleBase + " | Empleados",
    header: "Empleados",
    breadcrumbs: [
      { title: "Inicio", url: "/" },
      { title: "Empleados", url: "/" },
    ],
    headerExtraComponents: [
      <ButtonPrimary
        className="floating-btn"
        onPress={() => {
          Router.push("/abm/admin/empleados-kit/nuevoempleado");
        }}
        style={{
          padding: "6px",
          position: "static",
          display: "inline-block",
          minWidth: "100px",
          textAlign: "center",
        }}
        key={"header-btn"}
      >
        Nuevo +
      </ButtonPrimary>,
    ],
    hiddeArrowBack: true,
  },
  "/abm/admin/empleados-kit/nuevoempleado": {
    pageTitle: pageTitleBase + " | Nuevo Empleado",
    header: "Nuevo Empleado",
    breadcrumbs: [
      { title: "Inicio", url: "/" },
      { title: "Empleados", url: "/abm/admin/empleados-kit/" },
      { title: "Nuevo", url: "" },
    ],
  },
  "/abm/admin/empleados-kit/editarempleado/[dni]": {
    pageTitle: pageTitleBase + " | Editar Empleado",
    header: "Editar Empleado",
    breadcrumbs: [
      { title: "Inicio", url: "/abm/admin/empleados-kit/" },
      { title: "Empleados", url: "/abm/admin/empleados-kit/" },
      // { title: "Nuevo", url: "" },
    ],
  },
  "/abm/admin/empleados-kit/hijos/[id]": {
    pageTitle: pageTitleBase + " | Hijos de ",
    header: "Hijos de ",
    breadcrumbs: [
      { title: "Inicio", url: "/" },
      { title: "Empleados", url: "/abm/admin/empleados-kit/" },
      { title: "Hijos", url: "" },
    ],

    headerExtraComponents: [
      (router: NextRouter) => {
        const { id } = router.query;
        return (
          <ButtonPrimary
            className="floating-btn"
            onPress={() => {
              Router.push("/abm/admin/empleados-kit/hijos/agregarhijo/" + id);
            }}
            style={{
              padding: "6px",
              position: "static",
              display: "inline-block",
              minWidth: "100px",
              textAlign: "center",
            }}
            key={"header-btn"}
          >
            Nuevo +
          </ButtonPrimary>
        );
      },
    ],
    goBackTo: "/abm/admin/empleados-kit",
  },
  "/abm/admin/empleados-kit/hijos/agregarhijo/[id]": {
    pageTitle: pageTitleBase + " | Agregar Hijo ",
    header: "Agregar Hijo " + " ",
    breadcrumbs: [
      { title: "Inicio", url: "/" },
      { title: "Empleados", url: "/abm/admin/empleados-kit/" },
      { title: "Hijos", url: "/" },
      { title: "Nuevo", url: "" },
    ],
  },
  "/abm/admin/empleados-kit/hijos/editarhijo": {
    pageTitle: pageTitleBase + " | Editar hijo",
    header: "Editar hijo",
    breadcrumbs: [
      { title: "Inicio", url: "/" },
      { title: "Empleados", url: "/abm/admin/empleados-kit/" },
      { title: "Hijos", url: "" },
      { title: "Editar", url: "" },
    ],
  },

  "/abm/admin/campanas/cajanavidena/agregarcampana": {
    pageTitle: pageTitleBase + " | Agregar Campaña",
    header: "Agregar Campaña",
    breadcrumbs: [
      { title: "Inicio", url: "/" },
      { title: "Campañas", url: "/abm/admin/campanas" },
      { title: "Nueva", url: "" },
    ],
  },
  "/abm/admin/campanas/cajanavidena/editar": {
    pageTitle: pageTitleBase + " | Editar Caja Navideña",
    header: "Editar Caja Navideña",
    breadcrumbs: [
      { title: "Inicio", url: "/" },
      { title: "Campañas", url: "/abm/admin/campanas" },
      { title: "Editar", url: "" },
    ],
  },
  "/abm/admin/campanas/kitescolar/editar": {
    pageTitle: pageTitleBase + " | Editar Kit Escolar",
    header: "Editar Campaña Kit Escolar",
    breadcrumbs: [
      { title: "Inicio", url: "/" },
      { title: "Campañas", url: "/abm/admin/campanas" },
      { title: "Editar", url: "" },
    ],
  },
  "/abm/admin/campanas/cajanavidena/[id]": {
    pageTitle: pageTitleBase + " | Campaña Caja Navideña",
    header: "Campaña Caja Navideña",
    breadcrumbs: [
      { title: "Inicio", url: "/" },
      { title: "Campañas", url: "/abm/admin/campanas" },
    ],
    headerExtraComponents: [
      <ButtonPrimary
        className="floating-btn"
        onPress={() => {
          const { id } = Router.query;
          Router.push("/abm/admin/campanas/editar/" + id);
        }}
        style={{
          padding: "6px",
          position: "static",
          display: "inline-block",
          minWidth: "140px",
          textAlign: "center",
        }}
        key={"header-btn"}
      >
        Editar Campaña
      </ButtonPrimary>,
    ],
    goBackTo: "/abm/admin/campanas",
  },
  "/abm/admin/campanas/kitescolar/[id]": {
    pageTitle: pageTitleBase + " | Campaña Kit Escolar",
    header: "Campaña Kit Escolar",
    breadcrumbs: [
      { title: "Inicio", url: "/" },
      { title: "Campañas", url: "/abm/admin/campanas" },
    ],
    headerExtraComponents: [
      <ButtonPrimary
        className="floating-btn"
        onPress={() => {
          const { id } = Router.query;
          Router.push("/abm/admin/campanas/editar/" + id);
        }}
        style={{
          padding: "6px",
          position: "static",
          display: "inline-block",
          minWidth: "140px",
          textAlign: "center",
        }}
        key={"header-btn"}
      >
        Editar Campaña
      </ButtonPrimary>,
    ],
    goBackTo: "/abm/admin/campanas",
  },
  "/abm/admin/campanas/colonia/[id]": {
    pageTitle: pageTitleBase + " | Campaña Colonia de Vacaciones",
    header: "Campaña Colonia de Vacaciones",
    breadcrumbs: [
      { title: "Inicio", url: "/" },
      { title: "Campañas", url: "/abm/admin/campanas" },
    ],
    headerExtraComponents: [
      <ButtonPrimary
        className="floating-btn"
        onPress={() => {
          const { id } = Router.query;
          Router.push("/abm/admin/campanas/editar/" + id);
        }}
        style={{
          padding: "6px",
          position: "static",
          display: "inline-block",
          minWidth: "140px",
          textAlign: "center",
        }}
        key={"header-btn"}
      >
        Editar Campaña
      </ButtonPrimary>,
    ],
    goBackTo: "/abm/admin/campanas",
  },
  "/abm/admin/eventos/[id]": {
    pageTitle: pageTitleBase + " | Campaña Caja Navideña",
    header: "Campaña Caja Navideña",
    breadcrumbs: [
      { title: "Inicio", url: "/" },
      { title: "Campañas", url: "/abm/admin/campanas" },
    ],
    headerExtraComponents: [
      <ButtonPrimary
        className="floating-btn"
        onPress={() => {
          const { id } = Router.query;
          Router.push("/abm/admin/campanas/editar/" + id);
        }}
        style={{
          padding: "6px",
          position: "static",
          display: "inline-block",
          minWidth: "140px",
          textAlign: "center",
        }}
        key={"header-btn"}
      >
        Editar Campaña
      </ButtonPrimary>,
    ],
    goBackTo: "/abm/admin/campanas",
  },
  "/abm/admin/eventos": {
    pageTitle: pageTitleBase + " | Eventos",
    header: "Administrar Eventos",
    breadcrumbs: [
      { title: "Inicio", url: "/" },
      { title: "Eventos", url: "/abm/admin/eventos" },
    ],
    headerExtraComponents: [
      <ButtonPrimary
        className="floating-btn"
        onPress={() => {
          const { id } = Router.query;
          Router.push("/abm/admin/eventos/nuevoevento");
        }}
        style={{
          padding: "6px",
          position: "static",
          display: "inline-block",
          minWidth: "150px",
          textAlign: "center",
        }}
        key={"header-btn"}
      >
        Nuevo Evento
      </ButtonPrimary>,
    ],
    goBackTo: "/",
  },
  "/abm/admin/eventos/editar": {
    pageTitle: pageTitleBase + " | Eventos",
    header: "Eventos",
    breadcrumbs: [
      { title: "Inicio", url: "/" },
      { title: "Eventos", url: "/abm/admin/eventos" },
      { title: "Editar", url: "" },
    ],
  },
  "/abm/admin/campanas/cajanavidena": {
    pageTitle: pageTitleBase + " | Caja Navideña",
    header: "Caja Navideña",
    breadcrumbs: [
      { title: "Inicio", url: "/" },
      { title: "Campañas", url: "/abm/admin/campanas" },
    ],
  },
  "/abm/admin/reportes/kits": {
    pageTitle: pageTitleBase + " | Reportes",
    header: "Reportes",
    breadcrumbs: [
      // { title: "Inicio", url: "/" },
      // { title: "Reportes", url: "/abm/admin/reportes" },
    ],
    hiddeArrowBack: true,
  },
  "/abm/admin/reportes/cajas": {
    pageTitle: pageTitleBase + " | Reportes",
    header: "Reportes",
    breadcrumbs: [
      // { title: "Inicio", url: "/" },
      // { title: "Reportes", url: "/abm/admin/reportes" },
    ],

    hiddeArrowBack: true,
  },

  "/abm/colonia/busqueda": {
    pageTitle: pageTitleBase + " |  Colonia Buscar Empleado",
    header: "Buscar Empleado",
    breadcrumbs: [
      { title: "Buscar Usuario", url: "/abm/colonia/busqueda" },
      // { title: "Empleados", url: "/" },
    ],
    headerExtraComponents: [
      <ButtonPrimary
        className="floating-btn"
        onPress={() => {
          const { id } = Router.query;
          Router.push("/abm/colonia/crear");
        }}
        style={{
          padding: "6px",
          position: "static",
          display: "inline-block",
          minWidth: "176px",
          textAlign: "center",
        }}
        key={"header-btn"}
      >
        Cargar empleado
      </ButtonPrimary>,
    ],
    hiddeArrowBack: true,
  },
  "/abm/colonia/importar": {
    pageTitle: pageTitleBase + " | Colonia Cargar Beneficiarios",
    header: "Carga de Beneficiarios",
    breadcrumbs: [
      { title: "Inicio", url: "/" },
      { title: "Empleados", url: "/" },
    ],
    hiddeArrowBack: true,
  },
  "/abm/colonia/crear": {
    pageTitle: pageTitleBase + " | Colonia Crear Beneficiario",
    header: "Crear Beneficiario",
    breadcrumbs: [
      { title: "Inicio", url: "/" },
      { title: "Empleados", url: "/abm/colonia/busqueda" },
    ],
    hiddeArrowBack: true,
  },
  "/abm/colonia/editar/[id]": {
    pageTitle: pageTitleBase + " | Colonia Editar Beneficiario",
    header: "Editar Beneficiario ",
    breadcrumbs: [
      // { title: "Buscar Usuario", url: "/abm/colonia/busqueda" },
      // { title: "Empleados", url: "/abm/colonia/busqueda" },
    ],
    goBackTo: "/abm/colonia/busqueda",
  },
  "/abm/colonia/empleado/[id]": {
    pageTitle: pageTitleBase + " | Colonia Detalle de Empleado",
    header: "Detalle de Empleado",
    breadcrumbs: [
      // { title: "Buscar Usuario", url: "/abm/colonia/busqueda" },
      // { title: "Empleados", url: "/" },
    ],
    goBackTo: "/abm/colonia/busqueda",
  },

  "/abm/colonia/hijos/[id]": {
    pageTitle: pageTitleBase + " | Hijos de ",
    header: "Hijos",
    breadcrumbs: [
      { title: "Inicio", url: "/" },
      { title: "Empleados", url: "" },
      { title: "Hijos", url: "" },
    ],

    headerExtraComponents: [
      (router: NextRouter) => {
        const { id } = router.query;
        return (
          <ButtonPrimary
            className="floating-btn"
            onPress={() => {
              Router.push("/abm/colonia/hijos/agregarhijo/" + id);
            }}
            style={{
              padding: "6px",
              position: "static",
              display: "inline-block",
              minWidth: "100px",
              textAlign: "center",
            }}
            key={"header-btn"}
          >
            Nuevo +
          </ButtonPrimary>
        );
      },
    ],
    goBackTo: "/abm/colonia/busqueda",
  },
  "/abm/colonia/hijos/agregarhijo/[id]": {
    pageTitle: pageTitleBase + " | Agregar Hijo ",
    header: "Agregar Hijo " + " ",
    breadcrumbs: [
      { title: "Inicio", url: "/" },
      { title: "Empleados", url: "" },
      { title: "Hijos", url: "" },
      { title: "Nuevo", url: "" },
    ],
  },
  "/abm/colonia/hijos/editarhijo": {
    pageTitle: pageTitleBase + " | Editar hijo",
    header: "Editar hijo",
    breadcrumbs: [
      { title: "Inicio", url: "/" },
      { title: "Empleados", url: "" },
      { title: "Hijos", url: "" },
      { title: "Editar", url: "" },
    ],
    goBackTo: "/abm/colonia/busqueda",
  },

  "/abm/colonia/reportes": {
    pageTitle: pageTitleBase + " | Reportes",
    header: "Reportes",
    breadcrumbs: [
      { title: "Inicio", url: "/" },
      { title: "Reportes de colonias", url: "/abm/colonia/reportes" },
      // { title: "Buscar Usuario", url: "/abm/colonia/busqueda" },
      // { title: "Empleados", url: "/" },
    ],
    hiddeArrowBack: true,
  },
  "/abm/colonia/reportes/detallefactura/[id]": {
    pageTitle: pageTitleBase + " | Detalle de facturas",
    header: "Detalle factura",
    breadcrumbs: [
      { title: "Inicio", url: "/" },
      { title: "Reportes de colonias", url: "/abm/colonia/reportes" },
      { title: "Detalle de factura", url: "" },
      // { title: "Buscar Usuario", url: "/abm/colonia/busqueda" },
      // { title: "Empleados", url: "/" },
    ],
    goBackTo: "/abm/colonia/reportes",
  },
  "/abm/colonia/configuracion": {
    pageTitle: pageTitleBase + " | Configuración colonia",
    header: "Configuración",
    breadcrumbs: [
      { title: "Buscar Usuario", url: "/abm/colonia/busqueda" },
      { title: "Empleados", url: "/" },
    ],
    goBackTo: "/abm/colonia/busqueda",
  },
  "/abm/admin/administradores": {
    pageTitle: pageTitleBase + " | Administradores",
    header: "Administradores",
    breadcrumbs: [
      { title: "Inicio", url: "/" },
      { title: "Administradores", url: "" },
    ],
    headerExtraComponents: [
      <ButtonPrimary
        className="floating-btn"
        onPress={() => {
          Router.push("/abm/admin/administradores/nuevoAdministrador");
        }}
        style={{
          padding: "6px",
          position: "static",
          display: "inline-block",
          minWidth: "100px",
          textAlign: "center",
        }}
        key={"header-btn"}
      >
        Nuevo +
      </ButtonPrimary>,
    ],
    hiddeArrowBack: true,
  },
  "/abm/admin/administradores/": {
    pageTitle: pageTitleBase + " | Nuevo Administrador",
    header: "Nuevo Administrador",
    breadcrumbs: [
      { title: "Inicio", url: "/" },
      { title: "Administradores", url: "/abm/admin/administradores/" },
      { title: "Nuevo", url: "" },
    ],
  },
  "/abm/admin/administradores/editarAdministrador": {
    pageTitle: pageTitleBase + " | Editar Administrador",
    header: "Editar Administrador",
    breadcrumbs: [
      { title: "Inicio", url: "/" },
      { title: "Administradores", url: "/abm/admin/administradores/" },
      { title: "Editar", url: "" },
    ],
    goBackTo: "/abm/admin/administradores",
  },
  "/abm/admin/administradores/nuevoAdministrador": {
    pageTitle: pageTitleBase + " | Nuevo administradores",
    header: "Nuevo Administrador",
    breadcrumbs: [
      { title: "Inicio", url: "/" },
      { title: "Administradores", url: "/abm/admin/administradores/" },
      { title: "Nuevo", url: "" },
    ],
    goBackTo: "/abm/admin/administradores",
  },
  "/abm/admin/descuentos": {
    pageTitle: pageTitleBase + " | Administrar Cupones y Descuentos",
    header: "Cupones y Descuentos",
    breadcrumbs: [
      { title: "Inicio", url: "/" },
      { title: "Administrar", url: "/abm/admin/descuentos" },
      { title: "Cupones y descuentos", url: "/abm/admin/descuentos" },
    ],
  },
  "/abm/admin/descuentos/nuevodescuento": {
    pageTitle: pageTitleBase + " | Administrar Cupones y Descuentos",
    header: "Cupones y Descuentos",
    breadcrumbs: [
      { title: "Inicio", url: "/" },
      { title: "Administrar", url: "/abm/admin/descuentos" },
      { title: "Cupones y descuentos", url: "/abm/admin/descuentos" },
      { title: "Nuevo", url: "" },
    ],
    goBackTo: "/abm/admin/descuentos",
  },
  "/abm/admin/descuentos/editardescuento/[id]": {
    pageTitle: pageTitleBase + " | Administrar Cupones y Descuentos",
    header: "Cupones y Descuentos",
    breadcrumbs: [
      { title: "Inicio", url: "/" },
      { title: "Administrar", url: "/abm/admin/descuentos" },
      { title: "Cupones y descuentos", url: "/abm/admin/descuentos" },
      { title: "Editar", url: "" },
    ],
    goBackTo: "/abm/admin/descuentos",
  },
  "/abm/admin/insignias": {
    pageTitle: pageTitleBase + " | Reconocimientos",
    header: "Reconocimientos",
    breadcrumbs: [
      { title: "Inicio", url: "/" },
      { title: "Administrar", url: "/" },
      { title: "Reconocimientos", url: "/abm/admin/insignias" },
    ],
  },
  "/abm/admin/insignias/reporteria": {
    pageTitle: pageTitleBase + " | Reconocimientos",
    header: "Reportería",
    breadcrumbs: [
      { title: "Inicio", url: "/" },
      { title: "Administrar", url: "" },
      { title: "Reconocimientos", url: "/abm/admin/insignias" },
      { title: "Reportería", url: "/abm/admin/insignias/reporteria" },
    ],
    goBackTo: "/abm/admin/insignias",
  },
  "/abm/admin/insignias/cargaMasiva": {
    pageTitle: pageTitleBase + " | Carga Masiva de Reconocimientos",
    header: "Carga Masiva de Reconocimientos",
    breadcrumbs: [
      { title: "Inicio", url: "/" },
      { title: "Reconocimientos", url: "/abm/admin/insignias" },
      { title: "Carga Masiva", url: "/abm/admin/insignias/cargaMasiva" },
    ],
    goBackTo: "/abm/admin/insignias",
  },
  "/abm/admin/ultimasnovedades": {
    pageTitle: pageTitleBase + " | Ultimas Novedades",
    header: "Últimas novedades",
    breadcrumbs: [
      { title: "Inicio", url: "/" },
      { title: "Administrar", url: "" },
      { title: "Ultimas novedades", url: "/abm/admin/ultimasnovedades" },
    ],
  },
  "/abm/admin/ultimasnovedades/control": {
    pageTitle: pageTitleBase + " | Ultimas Novedades",
    header: "Últimas novedades",
    breadcrumbs: [
      { title: "Inicio", url: "/" },
      { title: "Administrar", url: "" },
      { title: "Ultimas novedades", url: "/abm/admin/ultimasnovedades" },
      { title: "Nueva", url: "/abm/admin/ultimasnovedades/control" },
    ],
    goBackTo: "/abm/admin/ultimasnovedades",
  },
  "/abm/admin/ultimasnovedades/editar/[id]": {
    pageTitle: pageTitleBase + " | Ultimas Novedades",
    header: "Últimas novedades",
    breadcrumbs: [
      { title: "Inicio", url: "/" },
      { title: "Administrar", url: "" },
      { title: "Ultimas novedades", url: "/abm/admin/ultimasnovedades" },
      { title: "Editar", url: "/abm/admin/ultimasnovedades/editar/[id]" },
    ],
    goBackTo: "/abm/admin/ultimasnovedades",
  },
  "/abm/admin/oficinas": {
    pageTitle: pageTitleBase + " | Oficinas",
    header: "Oficinas",
    breadcrumbs: [
      { title: "Inicio", url: "/" },
      { title: "Oficinas", url: "" },
    ],
    headerExtraComponents: [
      <ButtonPrimary
        className="floating-btn"
        onPress={() => {
          Router.push("/abm/admin/oficinas/nuevaOficina");
        }}
        style={{ padding: "6px" }}
        key={"header-btn"}
      >
        Nuevo +
      </ButtonPrimary>,
    ],
    hiddeArrowBack: true,
  },
  "/abm/admin/oficinas/": {
    pageTitle: pageTitleBase + " | Nueva Oficina",
    header: "Nueva Oficina",
    breadcrumbs: [
      { title: "Inicio", url: "/" },
      { title: "Oficinas", url: "/abm/admin/oficinas/" },
      { title: "Nuevo", url: "" },
    ],
  },
  "/abm/admin/oficinas/editarOficina": {
    pageTitle: pageTitleBase + " | Editar Oficina",
    header: "Editar Oficina",
    breadcrumbs: [
      { title: "Inicio", url: "/" },
      { title: "Oficinas", url: "/abm/admin/oficinas/" },
      { title: "Editar", url: "" },
    ],
  },
  "/abm/admin/oficinas/nuevaOficina": {
    pageTitle: pageTitleBase + " | Nueva Oficina",
    header: "Nueva Oficina",
    breadcrumbs: [
      { title: "Inicio", url: "/" },
      { title: "Oficinas", url: "/abm/admin/oficinas/" },
      { title: "Nuevo", url: "" },
    ],
  },
  "/abm/admin/gestionreferidos": {
    pageTitle: pageTitleBase + " | Gestión de bienes",
    header: "Solicitudes recibidas",
    breadcrumbs: [
      { title: "Inicio", url: "/" },
      { title: "Gestión de bienes", url: "/" },
      { title: "Solicitudes recibidas", url: "/abm/admin/gestionreferidos" },
    ],
  },
  "/abm/admin/gestionreferidos/[id]": {
    pageTitle: pageTitleBase + " | Gestión de bienes",
    header: "Detalle de solicitud",
    breadcrumbs: [
      { title: "Inicio", url: "/" },
      { title: "Gestión de bienes", url: "/" },
      { title: "Solicitudes recibidas", url: "/abm/admin/gestionreferidos" },
      { title: "Detalle de solicitud", url: "/abm/admin/gestionreferidos/[id]" },
    ],
  },
  "/abm/admin/gestionreferidos/referencias": {
    pageTitle: pageTitleBase + " | Gestión de bienes",
    header: "Referir bienes",
    breadcrumbs: [
      { title: "Inicio", url: "/" },
      { title: "Gestión de bienes", url: "/" },
      { title: "Referir bienes", url: "/abm/admin/gestionreferidos/referencias" },
    ],
  },
  "/abm/admin/gestionreferidos/referir": {
    pageTitle: pageTitleBase + " | Gestión de bienes",
    header: "Referir un bien",
    breadcrumbs: [
      { title: "Inicio", url: "/" },
      { title: "Gestión de bienes", url: "/" },
      { title: "Referir bienes", url: "/abm/admin/gestionreferidos/referencias" },
      { title: "Referir un bien", url: "/abm/admin/gestionreferidos/referir" },
    ],
  },
};

const protedtedRoutePath: {
  [key: string]: UserRole[];
} = {
  "/empleado/kitescolar": ["userKitRole"],
  "/empleado/coloniavacaciones": ["@telefonica"],
  // "/empleados/": ["userRole"],
  "/empleado/sorteos": ["@telefonica"],
  "/empleado/seguros": ["superAdminRole"],
  "/empleado/eventos": ["@telefonica"],
  "/empleado/cursos": ["superAdminRole"],
  "/empleado/empleado/bonos": ["@telefonica"],
  "/abm/facilitador/": ["facilitadorExternoRole", "facilitadorRole"],
  "/abm/admin/campanas": ["superAdminRole"],
  "/abm/admin/facilitadores": ["superAdminRole"],
  "/abm/admin/administradores": ["superAdminRole"],
  "/abm/admin/empleados": ["cajaAdminRole", "kitAdminRole"],
  "/abm/admin/empleados-kit": ["kitAdminRole"],
  "/abm/admin/importar": ["cajaAdminRole", "kitAdminRole"],
  "/abm/admin/importar/cajanavidena": ["cajaAdminRole"],
  "/abm/admin/reportes/kits": ["kitAdminRole"],
  "/abm/admin/reportes/boxes": ["cajaAdminRole"],
  "/abm/colonia": ["@telefonica"],
  // "/abm/colonia/hijos": ["coloniaAdminRole"],
  "/abm/colonia/reportes": ["@telefonica"],
  "abm/colonia/editarempleado": ["@telefonica"],
  "abm/colonia/importar": ["@telefonica"],
  "abm/colonia/crearEmpleado": ["@telefonica"],
  "abm/admin/sorteos": ["sorteo", "sorteoAdminRole"],
  "abm/admin/eventos": ["evento", "eventoAdminRole"],
  "/abm/admin/oficina": ["superAdminRole"],
  "/abm/admin/gestionreferidos": ["bienesAdminRole"],
  "/abm/admin/gestionreferidos/referencias": ["bienesAdminRole"],
  "/abm/admin/gestionreferidos/referir": ["bienesAdminRole"],
  "/abm/admin/descuentos": ["bonosAdminRole"],
  "/abm/admin/descuentos/nuevodescuento": ["bonosAdminRole"],
  "/abm/admin/descuentos/editardescuento": ["bonosAdminRole"],
};

const useRouterInfo: any = (customInfo?: Function): RouterInfo => {
  const [routes, setRoutes] = useState<any>(routesInfo);
  const router = useRouter();
  // Prefer `router.route` (route pattern) but fall back to `router.pathname`
  // and try to find the best matching key in `routes` when an exact match
  // isn't present. This helps when Next returns different values for route
  // vs pathname and avoids missing breadcrumbs/header data.
  const routeKey = router.route || router.pathname;
  let routeInfo = routes[routeKey];
  if (!routeInfo) {
    const pathname = router.pathname || routeKey;
    const keys = Object.keys(routes);
    const match = keys.find((k) => {
      const base = k.replace(/\[.*?\]/g, "");
      if (!base) return false;
      if (pathname === base) return true;
      // ensure base ends with slash for proper startsWith checks
      const baseNormalized = base.endsWith("/") ? base : base + "/";
      const pathNorm = pathname.endsWith("/") ? pathname : pathname + "/";
      return pathNorm.startsWith(baseNormalized);
    });
    routeInfo = match ? routes[match] : routes["default"];
  }
  routeInfo = typeof customInfo === "function" ? customInfo(routeInfo, router) : routeInfo;

  // Chequeo si la ruta es protegida y si el usuario tiene el rol necesario
  // Comentar la linea de abajo para deshabilitar el chequeo de roles
  const checkProtectedRoute = (userRoles: UserRole[]) => {
    let flag = true;
    const protectedRoutes = Object.keys(protedtedRoutePath);
    protectedRoutes.forEach((protectedRoute) => {
      // Es una ruta protegida
      if (router.pathname.includes(protectedRoute)) {
        // Chequeo si el usuario tiene el rol necesario
        const requiredRoles = protedtedRoutePath[protectedRoute];
        const hasRole = userRoles.some((role) => requiredRoles.includes(role));
        // Si no tiene el rol necesario, redirijo a home
        if (!hasRole) {
          flag = false;
        }
      }
    });
    return flag;
  };

  return { ...routeInfo, checkProtectedRoute };
};

export default useRouterInfo;
